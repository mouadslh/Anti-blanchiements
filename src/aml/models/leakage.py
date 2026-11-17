"""Future-invariance test of docs/evaluation_plan.md, section 2.4 (rule L-1).

A feature computed at time ``t`` must only depend on transactions dated at or before ``t``.
So the features of every event dated <= ``cutoff`` must be *identical* whether they are computed
on the full dataset or on the dataset truncated at ``cutoff`` (all later transactions removed).
Any difference proves that some feature used a later transaction.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd

from aml.models.features import MODEL_FEATURES, truncate_transactions

KEY = ["account_id", "tx_id", "side"]
Builder = Callable[[pd.DataFrame], pd.DataFrame]


@dataclass(frozen=True)
class LeakageFinding:
    feature: str
    cutoff: pd.Timestamp
    differing_rows: int
    example: tuple[str, str, str]


def check_future_invariance(
    transactions: pd.DataFrame,
    builder: Builder,
    cutoffs: Iterable[pd.Timestamp],
    features: Sequence[str] = MODEL_FEATURES,
) -> list[LeakageFinding]:
    """Return one finding per (cutoff, feature) that changes when the future is removed."""
    full = builder(transactions).set_index(KEY)
    findings: list[LeakageFinding] = []
    for cutoff in cutoffs:
        cutoff = pd.Timestamp(cutoff).tz_convert("UTC")
        truncated = builder(truncate_transactions(transactions, cutoff)).set_index(KEY)
        # Events with equal keys exist in both frames; the truncated one is a subset of the full one.
        reference = full.loc[truncated.index]
        for feature in features:
            left = reference[feature].to_numpy(dtype=float)
            right = truncated[feature].to_numpy(dtype=float)
            same = np.isclose(left, right, rtol=1e-9, atol=1e-9, equal_nan=True)
            if not same.all():
                first = truncated.index[int(np.flatnonzero(~same)[0])]
                findings.append(
                    LeakageFinding(feature, cutoff, int((~same).sum()), tuple(first))
                )
    return findings
