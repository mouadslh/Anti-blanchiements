"""Strict temporal split (docs/evaluation_plan.md, section 2).

Days are numbered from 1 (first simulated day). Blocks are contiguous and ordered in time:
warm-up, then training, then validation, then test. There is no random shuffling anywhere:
a row belongs to a block only because of its day.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

BLOCK_ORDER = ("warmup", "train", "validation", "test")


@dataclass(frozen=True)
class TemporalSplit:
    """Inclusive day ranges of the four blocks."""

    warmup: tuple[int, int]
    train: tuple[int, int]
    validation: tuple[int, int]
    test: tuple[int, int]

    def __post_init__(self) -> None:
        previous_end = 0
        for name in BLOCK_ORDER:
            start, end = self.range_of(name)
            if start > end:
                raise ValueError(f"block {name}: start day {start} is after end day {end}")
            if start != previous_end + 1:
                raise ValueError(
                    f"block {name} must start the day after the previous block "
                    f"(expected day {previous_end + 1}, got {start})"
                )
            previous_end = end

    @classmethod
    def from_config(cls, scoring: Mapping[str, Any]) -> TemporalSplit:
        split = scoring["evaluation"]["split"]
        return cls(
            warmup=tuple(split["warmup_days"]),
            train=tuple(split["train_days"]),
            validation=tuple(split["validation_days"]),
            test=tuple(split["test_days"]),
        )

    def range_of(self, block: str) -> tuple[int, int]:
        return getattr(self, block)

    def mask(self, days: np.ndarray | pd.Series, block: str) -> np.ndarray:
        start, end = self.range_of(block)
        values = np.asarray(days)
        return (values >= start) & (values <= end)

    def block_of(self, day: int) -> str | None:
        for name in BLOCK_ORDER:
            start, end = self.range_of(name)
            if start <= day <= end:
                return name
        return None

    def last_day(self, block: str) -> int:
        return self.range_of(block)[1]


def assert_chronological(frame: pd.DataFrame, split: TemporalSplit) -> None:
    """Raise if a training row is not strictly earlier than every validation/test row."""
    train = frame.loc[split.mask(frame["day"], "train"), "timestamp"]
    later = frame.loc[
        split.mask(frame["day"], "validation") | split.mask(frame["day"], "test"), "timestamp"
    ]
    if len(train) and len(later) and train.max() >= later.min():
        raise AssertionError("training rows overlap or follow validation/test rows")
