"""Causal account-day rows for model training and evaluation."""

from __future__ import annotations

import csv
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aml.simulator.labels import read_labels
from aml.simulator.normal import START
from aml.streaming.features import (
    AccountEvent,
    FeatureConfig,
    calculate_features,
    transaction_to_account_events,
)

FEATURE_NAMES = (
    "tx_count_1h",
    "total_amount_1h_mad",
    "distinct_counterparties_1h",
    "tx_count_24h",
    "total_amount_24h_mad",
    "distinct_counterparties_24h",
    "tx_count_7d",
    "total_amount_7d_mad",
    "distinct_counterparties_7d",
    "amount_to_avg_ratio",
    "near_threshold_share_24h",
    "near_threshold_share_7d",
    "cash_share_24h",
    "cash_share_7d",
    "inflow_outflow_ratio_24h",
    "avg_in_to_out_delay_s_24h",
    "distinct_cities_24h",
    "days_since_previous_tx",
    "current_channel_cash",
    "current_channel_international",
)


def _read_transactions(path: str | Path) -> dict[str, list[AccountEvent]]:
    grouped: dict[str, list[AccountEvent]] = defaultdict(list)
    with Path(path).open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            for event in transaction_to_account_events(row):
                grouped[event.account_id].append(event)
    for events in grouped.values():
        events.sort(key=lambda event: event.order_key)
    return grouped


def build_account_days(
    transactions_path: str | Path,
    labels_path: str | Path,
    *,
    reporting_threshold_mad: float = 100_000.0,
    history_days: int = 30,
    min_history_events: int = 3,
) -> list[dict[str, Any]]:
    """Use each account's last observed event in each UTC day as the prediction point.

    Labels only enter the target fields and are joined after feature construction. The feature
    function sees events up to and including the prediction transaction, never later events.
    """
    events_by_account = _read_transactions(transactions_path)
    intervals: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for label in read_labels(labels_path):
        if label["tx_id"]:
            continue
        start = datetime.fromisoformat(label["start_ts"])
        end = datetime.fromisoformat(label["end_ts"])
        intervals[label["account_id"]].append(
            {
                "start": start,
                "end": end,
                "case_id": label["case_id"],
                "scenario": label["scenario"],
                "sophistication": label["sophistication"],
            }
        )

    config = FeatureConfig(reporting_threshold_mad, history_days, min_history_events)
    rows: list[dict[str, Any]] = []
    for account_id, events in events_by_account.items():
        last_index_by_day: dict[int, int] = {}
        for index, event in enumerate(events):
            day = (event.timestamp.date() - START.date()).days + 1
            if 1 <= day <= 90:
                last_index_by_day[day] = index
        account_intervals = intervals.get(account_id, [])
        for day, index in sorted(last_index_by_day.items()):
            event = events[index]
            features = calculate_features(events[:index], event, config)
            active = [
                label
                for label in account_intervals
                if label["start"].date() <= event.timestamp.date() <= label["end"].date()
            ]
            rows.append(
                {
                    "account_id": account_id,
                    "tx_id": event.tx_id,
                    "as_of": event.timestamp.astimezone(UTC).isoformat().replace("+00:00", "Z"),
                    "day": day,
                    "label": int(bool(active)),
                    "active_cases": sorted({item["case_id"] for item in active}),
                    "active_scenarios": sorted({item["scenario"] for item in active}),
                    "active_sophistication": sorted(
                        {item["sophistication"] for item in active}
                    ),
                "active_case_starts": {
                    item["case_id"]: item["start"].isoformat() for item in active
                },
                "active_case_scenarios": {
                    item["case_id"]: item["scenario"] for item in active
                },
                "active_case_levels": {
                    item["case_id"]: item["sophistication"] for item in active
                },
                    "features": {name: features.get(name) for name in FEATURE_NAMES},
                }
            )
    rows.sort(key=lambda row: (row["day"], row["account_id"]))
    return rows


def temporal_masks(rows: list[dict[str, Any]], evaluation: dict[str, Any]) -> dict[str, list[int]]:
    """Return indices for the fixed chronological blocks in the evaluation plan."""
    blocks = {
        "train": evaluation["train_days"],
        "validation": evaluation["validation_days"],
        "test": evaluation["test_days"],
    }
    return {
        name: [
            index
            for index, row in enumerate(rows)
            if int(bounds[0]) <= row["day"] <= int(bounds[1])
        ]
        for name, bounds in blocks.items()
    }
