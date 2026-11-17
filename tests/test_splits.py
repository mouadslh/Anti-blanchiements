import numpy as np
import pandas as pd
import pytest

from aml.models.config import load_scoring_config
from aml.models.labels import positive_mask
from aml.models.pipeline import select_training_rows, training_labels
from aml.models.splits import TemporalSplit, assert_chronological

SPLIT = TemporalSplit.from_config(load_scoring_config())


def frame(days: list[int]) -> pd.DataFrame:
    origin = pd.Timestamp("2027-01-15", tz="UTC")
    return pd.DataFrame({
        "account_id": [f"acct-{i % 3:06d}" for i in range(len(days))],
        "day": days,
        "timestamp": [origin + pd.Timedelta(days=d - 1, hours=i % 24) for i, d in enumerate(days)],
    })


def test_blocks_match_the_evaluation_plan():
    assert (SPLIT.warmup, SPLIT.train, SPLIT.validation, SPLIT.test) == (
        (1, 7), (8, 56), (57, 72), (73, 90))


def test_every_day_belongs_to_exactly_one_block_in_time_order():
    days = np.arange(1, 91)
    masks = [SPLIT.mask(days, name) for name in ("warmup", "train", "validation", "test")]
    assert (np.sum(masks, axis=0) == 1).all()
    order = [SPLIT.block_of(int(d)) for d in days]
    assert order == sorted(order, key=("warmup", "train", "validation", "test").index)


@pytest.mark.parametrize("bad", [
    {"warmup": (1, 7), "train": (9, 56), "validation": (57, 72), "test": (73, 90)},   # gap
    {"warmup": (1, 7), "train": (7, 56), "validation": (57, 72), "test": (73, 90)},   # overlap
    {"warmup": (1, 7), "train": (8, 56), "validation": (57, 72), "test": (80, 73)},   # inverted
])
def test_invalid_splits_are_rejected(bad):
    with pytest.raises(ValueError):
        TemporalSplit(**bad)


def test_training_uses_only_the_training_block():
    events = frame(list(range(1, 91)))
    selected = events[select_training_rows(events, SPLIT)]
    assert selected["day"].min() == 8 and selected["day"].max() == 56


def test_selection_is_independent_of_row_order_so_nothing_is_shuffled():
    events = frame(list(range(1, 91)) * 2)
    shuffled = events.sample(frac=1.0, random_state=0)
    assert set(events[select_training_rows(events, SPLIT)].index) == set(
        shuffled[select_training_rows(shuffled, SPLIT)].index)


def test_chronology_check_fails_when_training_follows_validation():
    events = frame([10, 20, 60, 80])
    assert_chronological(events, SPLIT)
    broken = events.copy()
    broken.loc[0, "timestamp"] = broken["timestamp"].max() + pd.Timedelta(days=1)  # day-10 row, late
    with pytest.raises(AssertionError):
        assert_chronological(broken, SPLIT)


def test_labels_are_censored_at_the_end_of_the_training_block():
    labels = pd.DataFrame({
        "account_id": ["acct-000000", "acct-000001"], "start_day": [50, 60], "end_day": [65, 70],
        "case_id": ["c1", "c2"], "scenario": ["mule", "mule"], "sophistication": ["low", "low"],
    })
    events = pd.DataFrame({"account_id": ["acct-000000"] * 3 + ["acct-000001"], "day": [49, 55, 60, 60]})
    assert training_labels(events, labels, SPLIT).tolist() == [False, True, False, False]
    # without censoring, the day-60 rows would have been labelled with knowledge of later days
    assert positive_mask(events["account_id"], events["day"], labels).tolist() == [False, True, True, True]
