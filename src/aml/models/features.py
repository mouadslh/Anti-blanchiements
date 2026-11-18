"""Offline account-event features, aligned with the streaming definitions (contract C-06/C-07).

The Spark job computes the features one event at a time (``aml.streaming.features``). Training
needs them for millions of events, so this module recomputes the same quantities in a vectorised
way. ``tests/test_models_features.py`` checks that both implementations return the same values.

One row = one account event ``(account_id, tx_id, side)``. Every window is a *backward* window
ending at the event's own timestamp ``as_of``: ``(as_of - H, as_of]``, the event itself included
and events that sort after it in ``(timestamp, tx_id, side)`` order excluded. No quantity looks at
a later event (rule L-1 of ``docs/evaluation_plan.md``); ``aml.models.leakage`` checks it.

Two *extension* features are added for the rules (they are not in contract v1, see
``docs/models_baseline.md``):

* ``tx_count_7d_to_30d``: events dated in ``(as_of - 30 d, as_of - 7 d]`` (dormancy baseline);
* ``international_share_24h``: share of international transfers over 24 h.

and two descriptors of the triggering event itself (known at prediction time):
``current_amount_mad`` and ``current_flow_in``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from aml.models.config import load_scoring_config

HOUR_US = 3_600 * 1_000_000
DAY_US = 24 * HOUR_US
# Same horizons as aml.streaming.features.WINDOWS.
HORIZONS_US = {"1h": HOUR_US, "24h": DAY_US, "7d": 7 * DAY_US}

CASH_CHANNELS = ("cash_deposit", "cash_withdrawal")
TRANSFER_CHANNELS = ("transfer", "international_transfer")
CASH_COUNTERPARTY = "ext-cash"

CONTRACT_FEATURES = (
    "tx_count_1h", "tx_count_24h", "tx_count_7d",
    "total_amount_1h_mad", "total_amount_24h_mad", "total_amount_7d_mad",
    "distinct_counterparties_1h", "distinct_counterparties_24h", "distinct_counterparties_7d",
    "amount_to_avg_ratio",
    "near_threshold_share_24h", "near_threshold_share_7d",
    "cash_share_24h", "cash_share_7d",
    "inflow_outflow_ratio_24h", "avg_in_to_out_delay_s_24h", "distinct_cities_24h",
)
EXTENSION_FEATURES = ("tx_count_7d_to_30d", "international_share_24h")
EVENT_FEATURES = ("current_amount_mad", "current_flow_in")
# Inputs of the ML models. No identifier, no label, no time index (rule L-4).
MODEL_FEATURES = CONTRACT_FEATURES + EXTENSION_FEATURES + EVENT_FEATURES
KEY_COLUMNS = ("account_id", "tx_id", "side", "timestamp", "day")


@dataclass(frozen=True)
class FeatureParams:
    """Feature parameters. No default: values come from ``config/scoring.yaml`` (no hard-coded
    reporting threshold, which is a simulation assumption and not a legal figure)."""

    reporting_threshold_mad: float
    history_days: int
    min_history_events: int
    near_threshold_band: float
    baseline_window_days: tuple[int, int]

    @classmethod
    def from_config(cls, scoring: Mapping[str, Any]) -> FeatureParams:
        features = scoring["features"]
        return cls(
            reporting_threshold_mad=float(scoring["reporting_threshold"]),
            history_days=int(features["history_days"]),
            min_history_events=int(features["min_history_events"]),
            near_threshold_band=float(features["near_threshold_band"]),
            baseline_window_days=tuple(features["baseline_window_days"]),
        )


def _account_events(transactions: pd.DataFrame) -> dict[str, np.ndarray]:
    """Expand transactions to account events (same convention as the streaming job, C-05)."""
    timestamps = pd.to_datetime(transactions["timestamp"], utc=True).dt.as_unit("us")
    t_us = timestamps.astype("int64").to_numpy()
    source = transactions["source_account_id"].astype(str).to_numpy()
    target = transactions["target_account_id"].astype(str).to_numpy()
    tx_id = transactions["tx_id"].astype(str).to_numpy()
    channel = transactions["channel"].astype(str).to_numpy()
    city = transactions["city"].astype(str).to_numpy()
    cents = np.rint(transactions["amount"].to_numpy(dtype=float) * 100).astype(np.int64)
    internal = pd.Series(target).str.startswith("acct-").to_numpy()
    source_in = channel == "cash_deposit"

    return {
        "account": np.concatenate([source, target[internal]]),
        "tx_id": np.concatenate([tx_id, tx_id[internal]]),
        "side": np.concatenate([np.zeros(len(source), np.int8), np.ones(internal.sum(), np.int8)]),
        "t": np.concatenate([t_us, t_us[internal]]),
        "cents": np.concatenate([cents, cents[internal]]),
        "channel": np.concatenate([channel, channel[internal]]),
        "city": np.concatenate([city, city[internal]]),
        "counterparty": np.concatenate([target, source[internal]]),
        "flow_in": np.concatenate([source_in, np.ones(internal.sum(), bool)]),
    }


def _distinct_windows(
    starts: np.ndarray, t: np.ndarray, codes: np.ndarray, excluded: int, horizons: list[int]
) -> np.ndarray:
    """Distinct ``codes`` in ``(t_i - H, t_i]`` per account, for each horizon (two pointers)."""
    n = len(t)
    result = np.zeros((len(horizons), n), dtype=np.int32)
    t_list = t.tolist()
    code_list = codes.tolist()
    bounds = [*starts.tolist(), n]
    for segment in range(len(starts)):
        begin, end = bounds[segment], bounds[segment + 1]
        lefts = [begin] * len(horizons)
        counters: list[dict[int, int]] = [{} for _ in horizons]
        for i in range(begin, end):
            ti = t_list[i]
            code = code_list[i]
            for h, horizon in enumerate(horizons):
                counter = counters[h]
                if code != excluded:
                    counter[code] = counter.get(code, 0) + 1
                left = lefts[h]
                limit = ti - horizon
                while t_list[left] <= limit:
                    old = code_list[left]
                    if old != excluded:
                        remaining = counter[old] - 1
                        if remaining:
                            counter[old] = remaining
                        else:
                            del counter[old]
                    left += 1
                lefts[h] = left
                result[h, i] = len(counter)
    return result


def _window_sum(cumulative: np.ndarray, left: np.ndarray, position: np.ndarray) -> np.ndarray:
    return cumulative[position + 1] - cumulative[left]


def build_event_features(
    transactions: pd.DataFrame,
    params: FeatureParams | None = None,
    *,
    origin: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Features of every account event, sorted by ``(account_id, timestamp, tx_id, side)``.

    ``origin`` is the first simulated day (day 1); by default the date of the earliest
    transaction. Returned columns: ``KEY_COLUMNS`` then ``MODEL_FEATURES``.
    """
    params = params or FeatureParams.from_config(load_scoring_config())
    if transactions.empty:
        return pd.DataFrame(columns=[*KEY_COLUMNS, *MODEL_FEATURES])
    raw = _account_events(transactions)

    account_codes, account_names = pd.factorize(raw["account"], sort=True)
    tx_rank = pd.factorize(raw["tx_id"], sort=True)[0]
    order = np.lexsort((raw["side"], tx_rank, raw["t"], account_codes))
    account_codes = account_codes[order]
    names = np.asarray(account_names)[account_codes]
    tx_id = raw["tx_id"][order]
    side = raw["side"][order]
    t = raw["t"][order]
    cents = raw["cents"][order]
    channel = raw["channel"][order]
    flow_in = raw["flow_in"][order]
    city_codes = pd.factorize(raw["city"][order])[0]
    cp_codes, cp_names = pd.factorize(raw["counterparty"][order])
    cash_matches = np.flatnonzero(np.asarray(cp_names) == CASH_COUNTERPARTY)
    cash_code = int(cash_matches[0]) if len(cash_matches) else -1
    del raw
    n = len(t)

    amount = cents / 100.0
    epoch = pd.Timestamp("1970-01-01", tz="UTC")
    origin_day = (
        pd.Timestamp(origin).tz_convert("UTC")
        if origin is not None
        else pd.Timestamp(int(t.min()), unit="us", tz="UTC")
    ).normalize()
    origin_us = int((origin_day - epoch) // pd.Timedelta(microseconds=1))
    day = ((t - origin_us) // DAY_US + 1).astype(np.int32)

    # Per-account time offset: windows never cross accounts (SPAN > longest horizon + data span).
    t_rel = t - t.min()
    longest = max(params.history_days * DAY_US, 7 * DAY_US)
    span = int(t_rel.max()) + longest + 1
    key = account_codes.astype(np.int64) * span + t_rel
    if key.max() >= np.iinfo(np.int64).max // 2:
        raise OverflowError("time span times number of accounts is too large for the key trick")
    position = np.arange(n)
    starts = np.flatnonzero(np.r_[True, account_codes[1:] != account_codes[:-1]])

    def left_of(horizon_us: int) -> np.ndarray:
        # First index whose timestamp is strictly greater than as_of - horizon.
        return np.searchsorted(key, key - horizon_us, side="right")

    lefts = {name: left_of(h) for name, h in HORIZONS_US.items()}
    left_hist = left_of(params.history_days * DAY_US)

    cum = {
        "cents": np.concatenate([[0], np.cumsum(cents)]),
        "cash": np.concatenate([[0], np.cumsum(np.isin(channel, CASH_CHANNELS))]),
        "intl": np.concatenate([[0], np.cumsum(channel == "international_transfer")]),
        "in": np.concatenate([[0], np.cumsum(np.where(flow_in, cents, 0))]),
        "out": np.concatenate([[0], np.cumsum(np.where(flow_in, 0, cents))]),
    }
    threshold = params.reporting_threshold_mad
    near = (params.near_threshold_band * threshold <= amount) & (amount < threshold)
    cum["near"] = np.concatenate([[0], np.cumsum(near)])

    out: dict[str, np.ndarray] = {}
    for name in HORIZONS_US:
        left = lefts[name]
        out[f"tx_count_{name}"] = (position - left + 1).astype(np.int32)
        out[f"total_amount_{name}_mad"] = _window_sum(cum["cents"], left, position) / 100.0

    horizons = list(HORIZONS_US.values())
    distinct = _distinct_windows(starts, t, cp_codes, cash_code, horizons)
    for index, name in enumerate(HORIZONS_US):
        out[f"distinct_counterparties_{name}"] = distinct[index]
    out["distinct_cities_24h"] = _distinct_windows(starts, t, city_codes, -2, [DAY_US])[0]

    # amount_to_avg_ratio: mean of the previous events within history_days, current excluded.
    prior_count = position - left_hist
    prior_sum = (cum["cents"][position] - cum["cents"][left_hist]) / 100.0
    enough = prior_count >= params.min_history_events
    average = np.divide(prior_sum, prior_count, out=np.full(n, np.nan), where=prior_count > 0)
    valid = enough & (average > 0)
    out["amount_to_avg_ratio"] = np.where(
        valid, np.round(np.divide(amount, average, out=np.full(n, np.nan), where=valid), 6), np.nan
    )

    for name in ("24h", "7d"):
        count = out[f"tx_count_{name}"]
        out[f"near_threshold_share_{name}"] = _window_sum(cum["near"], lefts[name], position) / count
        out[f"cash_share_{name}"] = _window_sum(cum["cash"], lefts[name], position) / count

    inflow = _window_sum(cum["in"], lefts["24h"], position) / 100.0
    outflow = _window_sum(cum["out"], lefts["24h"], position) / 100.0
    out["inflow_outflow_ratio_24h"] = np.where(
        outflow > 0,
        np.round(np.divide(inflow, outflow, out=np.full(n, np.nan), where=outflow > 0), 6),
        np.nan,
    )

    # Delay between an outbound transfer and the latest earlier inbound transfer within 24 h.
    is_transfer = np.isin(channel, TRANSFER_CHANNELS)
    inbound_transfer = flow_in & is_transfer
    last_inbound = np.maximum.accumulate(np.where(inbound_transfer, position, -1))
    previous_inbound = np.concatenate([[-1], last_inbound[:-1]])
    has_previous = previous_inbound >= 0
    previous_key = np.where(has_previous, key[np.maximum(previous_inbound, 0)], -1)
    paired = (~flow_in) & is_transfer & has_previous & (previous_key > key - DAY_US)
    delay_s = np.where(paired, (key - previous_key) / 1_000_000.0, 0.0)
    cum_delay = np.concatenate([[0.0], np.cumsum(delay_s)])
    cum_paired = np.concatenate([[0], np.cumsum(paired)])
    paired_count = _window_sum(cum_paired, lefts["24h"], position)
    delay_total = _window_sum(cum_delay, lefts["24h"], position)
    out["avg_in_to_out_delay_s_24h"] = np.where(
        paired_count > 0,
        np.round(np.divide(delay_total, paired_count, out=np.full(n, np.nan), where=paired_count > 0), 3),
        np.nan,
    )

    low, high = params.baseline_window_days
    out["tx_count_7d_to_30d"] = (left_of(low * DAY_US) - left_of(high * DAY_US)).astype(np.int32)
    out["international_share_24h"] = _window_sum(cum["intl"], lefts["24h"], position) / out["tx_count_24h"]
    out["current_amount_mad"] = amount
    out["current_flow_in"] = flow_in.astype(np.int8)

    frame = pd.DataFrame(
        {
            "account_id": names,
            "tx_id": tx_id,
            "side": np.where(side == 0, "source", "target"),
            "timestamp": pd.to_datetime(t, unit="us", utc=True),
            "day": day,
        }
    )
    for column in MODEL_FEATURES:
        frame[column] = out[column]
    return frame


def truncate_transactions(transactions: pd.DataFrame, cutoff: pd.Timestamp) -> pd.DataFrame:
    """Keep only the transactions whose timestamp is at or before ``cutoff`` (UTC)."""
    stamps = pd.to_datetime(transactions["timestamp"], utc=True)
    return transactions.loc[stamps <= pd.Timestamp(cutoff).tz_convert("UTC")].reset_index(drop=True)
