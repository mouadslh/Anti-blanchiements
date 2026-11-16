"""Account-day labels from the simulator's ground truth (evaluation and training only).

The labels never reach the scoring path. A (account, day) pair is positive when the account
has a role in a case whose ``[start_ts, end_ts]`` interval touches that day (docs/evaluation_plan.md,
section 1). For training, intervals are *censored* at ``known_until_day`` (rule L-5): a label
is only used as it would have been known at the end of the training block.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

LABEL_COLUMNS = ("account_id", "start_day", "end_day", "case_id", "scenario", "sophistication")


def load_account_labels(path: str, origin: pd.Timestamp) -> pd.DataFrame:
    """Read the account-role rows of a labels CSV and convert the interval to day numbers."""
    raw = pd.read_csv(path, dtype=str, keep_default_na=False)
    accounts = raw[raw["tx_id"] == ""].copy()
    origin_day = pd.Timestamp(origin).tz_convert("UTC").normalize()
    for source, target in (("start_ts", "start_day"), ("end_ts", "end_day")):
        stamps = pd.to_datetime(accounts[source], utc=True).dt.normalize()
        accounts[target] = ((stamps - origin_day) / pd.Timedelta(days=1)).astype(int) + 1
    return accounts[list(LABEL_COLUMNS)].reset_index(drop=True)


def positive_mask(
    account_ids: np.ndarray | pd.Series,
    days: np.ndarray | pd.Series,
    labels: pd.DataFrame,
    *,
    known_until_day: int | None = None,
) -> np.ndarray:
    """Boolean array: is (account, day) inside an interval of ``labels``?

    With ``known_until_day`` the intervals are cut at that day and cases starting later are
    ignored, so that nothing learned after that day can label an earlier row.
    """
    accounts = np.asarray(account_ids)
    day_values = np.asarray(days)
    result = np.zeros(len(accounts), dtype=bool)
    # Only the rows of labelled accounts can be positive: work on that small subset.
    candidates = np.flatnonzero(np.isin(accounts, labels["account_id"].to_numpy()))
    subset_accounts = accounts[candidates]
    subset_days = day_values[candidates]
    subset_result = np.zeros(len(candidates), dtype=bool)
    for row in labels.itertuples(index=False):
        if known_until_day is not None and row.start_day > known_until_day:
            continue
        end_day = row.end_day if known_until_day is None else min(row.end_day, known_until_day)
        subset_result |= (
            (subset_accounts == row.account_id)
            & (subset_days >= row.start_day)
            & (subset_days <= end_day)
        )
    result[candidates] = subset_result
    return result
