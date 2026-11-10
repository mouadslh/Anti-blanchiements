"""Validation légère des messages selon la proposition de contrat v1."""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any


class SchemaValidationError(ValueError):
    """Raised when a message does not match the proposed data contract."""


TRANSACTION_CHANNELS = {
    "cash_deposit",
    "cash_withdrawal",
    "transfer",
    "card",
    "international_transfer",
}
CUSTOMER_TYPES = {"salaried", "student", "merchant", "company"}

TRANSACTION_FIELDS = {
    "tx_id",
    "timestamp",
    "source_account_id",
    "target_account_id",
    "amount",
    "currency",
    "channel",
    "source_customer_type",
    "city",
}
FEATURE_FIELDS = {"account_id", "window_start", "window_end", "features"}
SCORE_FIELDS = {"account_id", "tx_id", "risk_score", "model_versions", "ts"}
ALERT_FIELDS = SCORE_FIELDS | {"explanation"}


def _object(payload: Any, expected_fields: set[str], schema_name: str) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        raise SchemaValidationError(f"{schema_name} must be a JSON object")
    missing = expected_fields - payload.keys()
    extra = payload.keys() - expected_fields
    if missing:
        raise SchemaValidationError(f"{schema_name} missing fields: {', '.join(sorted(missing))}")
    if extra:
        raise SchemaValidationError(f"{schema_name} has unexpected fields: {', '.join(sorted(extra))}")
    return payload


def _non_empty_string(value: Any, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise SchemaValidationError(f"{field} must be a non-empty string")


def _utc_timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or "T" not in value:
        raise SchemaValidationError(f"{field} must be an ISO-8601 timestamp in UTC")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise SchemaValidationError(f"{field} must be a valid ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise SchemaValidationError(f"{field} must include a UTC timezone")
    return parsed


def _number(value: Any, field: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise SchemaValidationError(f"{field} must be a number")
    if isinstance(value, float) and not math.isfinite(value):
        raise SchemaValidationError(f"{field} must be finite")
    result = Decimal(str(value))
    if not result.is_finite():
        raise SchemaValidationError(f"{field} must be finite")
    return result


def validate_transaction(payload: Any) -> Mapping[str, Any]:
    """Validate a transaction event. Labels and unknown fields are rejected."""
    event = _object(payload, TRANSACTION_FIELDS, "transaction")
    for field in ("tx_id", "source_account_id", "target_account_id", "currency", "city"):
        _non_empty_string(event[field], field)
    _utc_timestamp(event["timestamp"], "timestamp")
    _number(event["amount"], "amount")
    if not isinstance(event["channel"], str) or event["channel"] not in TRANSACTION_CHANNELS:
        raise SchemaValidationError("channel is not supported by the contract")
    if (
        not isinstance(event["source_customer_type"], str)
        or event["source_customer_type"] not in CUSTOMER_TYPES
    ):
        raise SchemaValidationError("source_customer_type is not supported by the contract")
    return event


def validate_features(payload: Any) -> Mapping[str, Any]:
    """Validate the proposed account/window feature message shape."""
    event = _object(payload, FEATURE_FIELDS, "features")
    _non_empty_string(event["account_id"], "account_id")
    start = _utc_timestamp(event["window_start"], "window_start")
    end = _utc_timestamp(event["window_end"], "window_end")
    if end < start:
        raise SchemaValidationError("window_end must be at or after window_start")
    if not isinstance(event["features"], Mapping):
        raise SchemaValidationError("features must be a JSON object")
    return event


def _validate_score_fields(payload: Any, schema_name: str) -> Mapping[str, Any]:
    event = _object(payload, SCORE_FIELDS, schema_name)
    _non_empty_string(event["account_id"], "account_id")
    _non_empty_string(event["tx_id"], "tx_id")
    score = _number(event["risk_score"], "risk_score")
    if not Decimal(0) <= score <= Decimal(1):
        raise SchemaValidationError("risk_score must be between 0 and 1")
    if not isinstance(event["model_versions"], Mapping) or not all(
        isinstance(name, str) and isinstance(version, str)
        for name, version in event["model_versions"].items()
    ):
        raise SchemaValidationError("model_versions must map model names to version strings")
    _utc_timestamp(event["ts"], "ts")
    return event


def validate_score(payload: Any) -> Mapping[str, Any]:
    """Validate a score message as specified by the master prompt."""
    return _validate_score_fields(payload, "score")


def validate_alert(payload: Any) -> Mapping[str, Any]:
    """Validate the proposed alert message shape."""
    event = _object(payload, ALERT_FIELDS, "alert")
    _validate_score_fields({key: event[key] for key in SCORE_FIELDS}, "alert")
    if not isinstance(event["explanation"], Mapping):
        raise SchemaValidationError("explanation must be a JSON object")
    return event


def validate_message(topic: str, payload: Any) -> Mapping[str, Any]:
    """Dispatch validation by Kafka topic name."""
    validators = {
        "transactions": validate_transaction,
        "features": validate_features,
        "scores": validate_score,
        "alerts": validate_alert,
    }
    try:
        validator = validators[topic]
    except KeyError as exc:
        raise SchemaValidationError(f"unknown topic: {topic}") from exc
    return validator(payload)
