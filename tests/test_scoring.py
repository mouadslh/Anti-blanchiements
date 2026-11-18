import csv

from aml.scoring.dataset import FEATURE_NAMES, build_account_days, temporal_masks
from aml.scoring.models import rule_prediction
from aml.simulator.labels import LABEL_FIELDS


def write_transactions(path, rows):
    fields = (
        "tx_id", "timestamp", "source_account_id", "target_account_id", "amount",
        "currency", "channel", "source_customer_type", "city",
    )
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_labels(path, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=LABEL_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def test_account_day_dataset_is_causal_and_joins_interval_labels(tmp_path):
    transactions = tmp_path / "transactions.csv"
    labels = tmp_path / "labels.csv"
    write_transactions(
        transactions,
        [
            {
                "tx_id": "t1", "timestamp": "2027-01-15T12:00:00Z",
                "source_account_id": "acct-000001", "target_account_id": "ext-000001",
                "amount": 100, "currency": "MAD", "channel": "transfer",
                "source_customer_type": "student", "city": "Rabat",
            },
            {
                "tx_id": "t2", "timestamp": "2027-01-16T12:30:00Z",
                "source_account_id": "acct-000001", "target_account_id": "ext-cash",
                "amount": 100000, "currency": "MAD", "channel": "cash_deposit",
                "source_customer_type": "student", "city": "Rabat",
            },
        ],
    )
    write_labels(
        labels,
        [{
            "account_id": "acct-000001", "tx_id": "", "scenario": "structuring",
            "role": "originator", "start_ts": "2027-01-15T00:00:00Z",
            "end_ts": "2027-01-15T23:59:59Z", "case_id": "case-001",
            "sophistication": "medium",
        }],
    )
    rows = build_account_days(transactions, labels)
    first = next(row for row in rows if row["day"] == 1)
    second = next(row for row in rows if row["day"] == 2)

    assert first["label"] == 1
    assert first["active_cases"] == ["case-001"]
    assert second["label"] == 0
    assert second["features"]["days_since_previous_tx"] == 1.020833
    assert second["features"]["current_channel_cash"] == 1.0
    assert set(second["features"]) == set(FEATURE_NAMES)
    assert "account_id" not in second["features"]

    truncated = tmp_path / "transactions_until_day_1.csv"
    write_transactions(truncated, [
        {
            "tx_id": "t1", "timestamp": "2027-01-15T12:00:00Z",
            "source_account_id": "acct-000001", "target_account_id": "ext-000001",
            "amount": 100, "currency": "MAD", "channel": "transfer",
            "source_customer_type": "student", "city": "Rabat",
        },
    ])
    truncated_first = build_account_days(truncated, labels)[0]
    assert first["features"] == truncated_first["features"]


def test_temporal_split_boundaries_are_disjoint():
    rows = [{"day": day} for day in range(1, 91)]
    masks = temporal_masks(
        rows,
        {"train_days": [8, 56], "validation_days": [57, 72], "test_days": [73, 90]},
    )
    assert (rows[masks["train"][0]]["day"], rows[masks["train"][-1]]["day"]) == (8, 56)
    assert (rows[masks["validation"][0]]["day"], rows[masks["validation"][-1]]["day"]) == (57, 72)
    assert (rows[masks["test"][0]]["day"], rows[masks["test"][-1]]["day"]) == (73, 90)
    assert not (set(masks["train"]) & set(masks["validation"]))
    assert not (set(masks["validation"]) & set(masks["test"]))


def test_rule_baseline_explains_structuring_and_dormant_activation():
    features = {
        "tx_count_1h": 1,
        "tx_count_7d": 5,
        "near_threshold_share_7d": 0.6,
        "cash_share_7d": 0.8,
        "avg_in_to_out_delay_s_24h": None,
        "inflow_outflow_ratio_24h": 0.0,
        "days_since_previous_tx": 20.0,
        "amount_to_avg_ratio": 4.0,
        "total_amount_24h_mad": 120000,
        "current_channel_cash": 1,
        "current_channel_international": 0,
    }
    score, fired = rule_prediction(features)
    assert score == 0.95
    assert fired == ["structuring", "dormant_then_active", "high_risk_channel"]
