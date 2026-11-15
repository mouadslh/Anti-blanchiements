"""Deterministic per-account, per-transaction AML feature calculations."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

WINDOWS = {"1h": timedelta(hours=1), "24h": timedelta(hours=24), "7d": timedelta(days=7)}
CASH_CHANNELS = {"cash_deposit", "cash_withdrawal"}
TRANSFER_CHANNELS = {"transfer", "international_transfer"}


@dataclass(frozen=True)
class AccountEvent:
    account_id: str
    tx_id: str
    timestamp: datetime
    side: str
    amount: float
    channel: str
    counterparty: str
    city: str
    flow: str

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() != timedelta(0):
            raise ValueError("timestamp must be timezone-aware UTC")
        if self.side not in {"source", "target"}:
            raise ValueError("side must be 'source' or 'target'")
        if self.flow not in {"in", "out"}:
            raise ValueError("flow must be 'in' or 'out'")
        if self.amount <= 0:
            raise ValueError("amount must be positive")

    @property
    def order_key(self) -> tuple[datetime, str, str]:
        return self.timestamp, self.tx_id, self.side


@dataclass(frozen=True)
class FeatureConfig:
    reporting_threshold_mad: float = 100_000.0
    history_days: int = 30
    min_history_events: int = 3

    def __post_init__(self) -> None:
        if self.reporting_threshold_mad <= 0:
            raise ValueError("reporting_threshold_mad must be positive")
        if self.history_days < 7:
            raise ValueError("history_days must be at least 7 to cover the longest feature window")
        if self.min_history_events < 1:
            raise ValueError("min_history_events must be positive")


def transaction_to_account_events(transaction: dict[str, Any]) -> list[AccountEvent]:
    """Expand one transaction to source and, when internal, target account events.

    Cash operations are represented with the customer account as ``source`` in contract
    v1; cash deposits therefore increase inflow and withdrawals increase outflow.
    """
    timestamp = datetime.fromisoformat(transaction["timestamp"].replace("Z", "+00:00"))
    channel = transaction["channel"]
    source_id = transaction["source_account_id"]
    target_id = transaction["target_account_id"]
    amount = float(transaction["amount"])
    source_flow = "in" if channel == "cash_deposit" else "out"
    events = [
        AccountEvent(
            account_id=source_id,
            tx_id=transaction["tx_id"],
            timestamp=timestamp,
            side="source",
            amount=amount,
            channel=channel,
            counterparty=target_id,
            city=transaction["city"],
            flow=source_flow,
        )
    ]
    if target_id.startswith("acct-"):
        events.append(
            AccountEvent(
                account_id=target_id,
                tx_id=transaction["tx_id"],
                timestamp=timestamp,
                side="target",
                amount=amount,
                channel=channel,
                counterparty=source_id,
                city=transaction["city"],
                flow="in",
            )
        )
    return events


def _within(event: AccountEvent, as_of: datetime, horizon: timedelta) -> bool:
    return as_of - horizon < event.timestamp <= as_of


def calculate_features(
    history: Iterable[AccountEvent], current: AccountEvent, config: FeatureConfig
) -> dict[str, float | int | None]:
    """Calculate the contract's backward-looking features, including ``current``.

    ``history`` must contain only earlier events in deterministic ``(timestamp, tx_id, side)``
    order. Future events are ignored defensively so a caller cannot introduce leakage.
    """
    ordered_history = sorted(
        (event for event in history if event.order_key < current.order_key),
        key=lambda event: event.order_key,
    )
    event_history = [*ordered_history, current]
    as_of = current.timestamp
    prior = [
        event
        for event in ordered_history
        if as_of - timedelta(days=config.history_days) < event.timestamp <= as_of
    ]
    prior_amount_average = (
        sum(event.amount for event in prior) / len(prior)
        if len(prior) >= config.min_history_events
        else None
    )
    threshold = config.reporting_threshold_mad
    features: dict[str, float | int | None] = {}

    for name, horizon in WINDOWS.items():
        events = [event for event in event_history if _within(event, as_of, horizon)]
        features[f"tx_count_{name}"] = len(events)
        features[f"total_amount_{name}_mad"] = round(sum(event.amount for event in events), 2)
        features[f"distinct_counterparties_{name}"] = len(
            {event.counterparty for event in events if event.counterparty != "ext-cash"}
        )

    features["amount_to_avg_ratio"] = (
        round(current.amount / prior_amount_average, 6)
        if prior_amount_average and prior_amount_average > 0
        else None
    )

    for name in ("24h", "7d"):
        events = [event for event in event_history if _within(event, as_of, WINDOWS[name])]
        features[f"near_threshold_share_{name}"] = (
            sum(0.9 * threshold <= event.amount < threshold for event in events) / len(events)
            if events
            else None
        )
        features[f"cash_share_{name}"] = (
            sum(event.channel in CASH_CHANNELS for event in events) / len(events)
            if events
            else None
        )

    day_events = [event for event in event_history if _within(event, as_of, WINDOWS["24h"])]
    inflow = sum(event.amount for event in day_events if event.flow == "in")
    outflow = sum(event.amount for event in day_events if event.flow == "out")
    features["inflow_outflow_ratio_24h"] = round(inflow / outflow, 6) if outflow else None

    delays: list[float] = []
    for outbound in day_events:
        if outbound.flow != "out" or outbound.channel not in TRANSFER_CHANNELS:
            continue
        inbound_before = [
            event
            for event in event_history
            if event.flow == "in"
            and event.channel in TRANSFER_CHANNELS
            and event.order_key < outbound.order_key
            and _within(event, outbound.timestamp, WINDOWS["24h"])
        ]
        if inbound_before:
            previous = max(inbound_before, key=lambda event: event.order_key)
            delays.append((outbound.timestamp - previous.timestamp).total_seconds())
    features["avg_in_to_out_delay_s_24h"] = round(sum(delays) / len(delays), 3) if delays else None
    features["distinct_cities_24h"] = len({event.city for event in day_events})
    return features


def as_feature_message(event: AccountEvent, features: dict[str, Any]) -> dict[str, Any]:
    """Build the proposed C-06 message; no label/ground-truth fields are accepted."""
    return {
        "account_id": event.account_id,
        "tx_id": event.tx_id,
        "side": event.side,
        "as_of": event.timestamp.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "feature_version": "1",
        "features": features,
    }


def event_state_dict(event: AccountEvent) -> dict[str, Any]:
    data = asdict(event)
    data["timestamp"] = event.timestamp.astimezone(UTC).isoformat(timespec="microseconds")
    return data


def event_from_state(data: dict[str, Any]) -> AccountEvent:
    return AccountEvent(
        **{
            **data,
            "timestamp": datetime.fromisoformat(data["timestamp"]),
        }
    )

