import numpy as np
import pandas as pd
import pytest
from synthetic_data import ORIGIN, make_transactions

from aml.models.config import load_scoring_config
from aml.models.features import (
    CONTRACT_FEATURES,
    FeatureParams,
    build_event_features,
)
from aml.streaming.features import FeatureConfig, calculate_features, transaction_to_account_events

SCORING = load_scoring_config()
PARAMS = FeatureParams.from_config(SCORING)


def test_offline_features_equal_the_streaming_definitions():
    """The vectorised builder returns the values of aml.streaming.features, event by event."""
    transactions = make_transactions(seed=1, threshold=PARAMS.reporting_threshold_mad)
    features = build_event_features(transactions, PARAMS, origin=ORIGIN).set_index(
        ["account_id", "tx_id", "side"]
    )
    per_account: dict[str, list] = {}
    for record in transactions.to_dict("records"):
        for event in transaction_to_account_events(record):
            per_account.setdefault(event.account_id, []).append(event)
    config = FeatureConfig(
        reporting_threshold_mad=PARAMS.reporting_threshold_mad,
        history_days=PARAMS.history_days,
        min_history_events=PARAMS.min_history_events,
    )
    checked = 0
    for account, events in per_account.items():
        events.sort(key=lambda event: event.order_key)
        for index, current in enumerate(events):
            expected = calculate_features(events[:index], current, config)
            row = features.loc[(account, current.tx_id, current.side)]
            for name in CONTRACT_FEATURES:
                got = row[name]
                if expected[name] is None:
                    assert np.isnan(got), (account, current.tx_id, name, got)
                else:
                    assert got == pytest.approx(expected[name], rel=1e-6, abs=1e-6), (
                        account, current.tx_id, name)
            checked += 1
    assert checked == len(features) > 500


def test_hand_made_structuring_account():
    threshold = PARAMS.reporting_threshold_mad
    rows = [
        {"tx_id": f"tx-{i:08d}", "timestamp": f"2027-02-01T{9 + i:02d}:00:00Z",
         "source_account_id": "acct-000001", "target_account_id": "ext-cash",
         "amount": round(0.95 * threshold, 2), "channel": "cash_deposit", "city": "Rabat"}
        for i in range(1, 4)
    ]
    frame = build_event_features(pd.DataFrame(rows), PARAMS, origin=ORIGIN)
    last = frame.iloc[-1]
    assert last["tx_count_24h"] == 3 and last["tx_count_1h"] == 1
    assert last["near_threshold_share_24h"] == 1.0 and last["cash_share_24h"] == 1.0
    assert last["total_amount_24h_mad"] == pytest.approx(3 * round(0.95 * threshold, 2))
    assert last["distinct_counterparties_24h"] == 0  # ext-cash is not a counterparty
    assert last["tx_count_7d_to_30d"] == 0
    assert np.isnan(last["inflow_outflow_ratio_24h"])  # deposits are inflows, no outflow: null
    assert last["current_flow_in"] == 1


def test_day_index_starts_at_one_on_the_origin():
    transactions = make_transactions(seed=2, days=3)
    frame = build_event_features(transactions, PARAMS, origin=ORIGIN)
    assert frame["day"].min() == 1
    assert frame.loc[frame["timestamp"] < ORIGIN + pd.Timedelta(days=1), "day"].eq(1).all()
    burst = frame.loc[frame["timestamp"] >= ORIGIN + pd.Timedelta(days=25), "day"]
    assert burst.eq(26).all() and len(burst) > 0  # helper adds a burst on the 26th day


def test_extension_features_are_documented_as_extensions():
    from aml.models.features import EXTENSION_FEATURES

    assert set(EXTENSION_FEATURES).isdisjoint(CONTRACT_FEATURES)
