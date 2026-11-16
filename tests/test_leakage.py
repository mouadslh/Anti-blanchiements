"""Future-invariance test (docs/evaluation_plan.md 2.4): detects features that look ahead."""

import pandas as pd
import pytest
from synthetic_data import ORIGIN, make_transactions

from aml.models.config import load_scoring_config
from aml.models.features import MODEL_FEATURES, FeatureParams, build_event_features
from aml.models.leakage import check_future_invariance

PARAMS = FeatureParams.from_config(load_scoring_config())
CUTOFFS = [ORIGIN + pd.Timedelta(days=day, hours=7, minutes=13) for day in (8, 16, 26, 33)]


def honest(frame: pd.DataFrame) -> pd.DataFrame:
    return build_event_features(frame, PARAMS, origin=ORIGIN)


@pytest.fixture(scope="module")
def transactions() -> pd.DataFrame:
    return make_transactions(seed=5, threshold=PARAMS.reporting_threshold_mad)


def test_project_features_do_not_use_future_information(transactions):
    assert check_future_invariance(transactions, honest, CUTOFFS) == []


def test_detects_a_feature_built_on_the_whole_period(transactions):
    """Negative control 1: an account-level mean over the full dataset (typical leak)."""
    def leaky(frame: pd.DataFrame) -> pd.DataFrame:
        events = honest(frame)
        events["total_amount_7d_mad"] = events.groupby("account_id")["current_amount_mad"].transform("mean")
        return events

    findings = check_future_invariance(transactions, leaky, CUTOFFS)
    assert {finding.feature for finding in findings} == {"total_amount_7d_mad"}


def test_detects_a_feature_that_looks_at_the_next_event(transactions):
    """Negative control 2: a feature taken from the account's next event (forward look)."""
    def leaky(frame: pd.DataFrame) -> pd.DataFrame:
        events = honest(frame)
        events["tx_count_1h"] = events.groupby("account_id")["current_amount_mad"].shift(-1)
        return events

    findings = check_future_invariance(transactions, leaky, CUTOFFS, features=["tx_count_1h"])
    assert findings and {finding.feature for finding in findings} == {"tx_count_1h"}
    assert all(finding.differing_rows > 0 for finding in findings)


def test_no_model_input_is_an_identifier_or_a_label_or_a_time_index():
    forbidden = ("account", "tx_id", "case", "scenario", "label", "role", "day", "timestamp")
    assert not [name for name in MODEL_FEATURES if any(word in name for word in forbidden)]
