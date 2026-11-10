"""Contract validation tests for the Phase 2 message schemas."""

from decimal import Decimal

import pytest

from aml.common.schemas import (
    SchemaValidationError,
    validate_alert,
    validate_features,
    validate_message,
    validate_score,
    validate_transaction,
)


@pytest.fixture
def transaction_event() -> dict[str, object]:
    return {
        "tx_id": "tx-1",
        "timestamp": "2026-01-15T10:30:00Z",
        "source_account_id": "acct-1",
        "target_account_id": "acct-2",
        "amount": Decimal("1250.50"),
        "currency": "MAD",
        "channel": "transfer",
        "source_customer_type": "salaried",
        "city": "Casablanca",
    }


def test_valid_transaction_matches_master_contract(transaction_event: dict[str, object]) -> None:
    assert validate_transaction(transaction_event) == transaction_event


@pytest.mark.parametrize(
    "change",
    [
        {"timestamp": "2026-01-15T10:30:00"},
        {"timestamp": "2026-01-15T10:30:00+01:00"},
        {"channel": "unknown"},
        {"source_customer_type": "unknown"},
        {"amount": True},
        {"currency": ""},
        {"ground_truth": True},
    ],
)
def test_invalid_transaction_is_rejected(
    transaction_event: dict[str, object], change: dict[str, object]
) -> None:
    transaction_event.update(change)
    with pytest.raises(SchemaValidationError):
        validate_transaction(transaction_event)


def test_missing_transaction_field_is_rejected(transaction_event: dict[str, object]) -> None:
    del transaction_event["tx_id"]
    with pytest.raises(SchemaValidationError, match="missing fields"):
        validate_transaction(transaction_event)


def test_valid_feature_message() -> None:
    assert validate_features(
        {
            "account_id": "acct-1",
            "window_start": "2026-01-15T10:00:00Z",
            "window_end": "2026-01-15T11:00:00Z",
            "features": {"transaction_count": 4},
        }
    )


def test_feature_window_must_not_be_reversed() -> None:
    with pytest.raises(SchemaValidationError, match="window_end"):
        validate_features(
            {
                "account_id": "acct-1",
                "window_start": "2026-01-15T11:00:00Z",
                "window_end": "2026-01-15T10:00:00Z",
                "features": {},
            }
        )


def test_valid_score_and_alert_messages() -> None:
    score = {
        "account_id": "acct-1",
        "tx_id": "tx-1",
        "risk_score": 0.85,
        "model_versions": {"rules": "v1"},
        "ts": "2026-01-15T11:00:00Z",
    }
    assert validate_score(score)
    assert validate_alert({**score, "explanation": {"summary_fr": "Activité à examiner"}})


@pytest.mark.parametrize("risk_score", [-0.1, 1.1, float("nan")])
def test_score_out_of_range_or_non_finite_is_rejected(risk_score: float) -> None:
    with pytest.raises(SchemaValidationError):
        validate_score(
            {
                "account_id": "acct-1",
                "tx_id": "tx-1",
                "risk_score": risk_score,
                "model_versions": {},
                "ts": "2026-01-15T11:00:00Z",
            }
        )


def test_topic_dispatch_rejects_labels_in_transaction_stream(
    transaction_event: dict[str, object],
) -> None:
    transaction_event["scenario"] = "structuring"
    with pytest.raises(SchemaValidationError, match="unexpected fields"):
        validate_message("transactions", transaction_event)
