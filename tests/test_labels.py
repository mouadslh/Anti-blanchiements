"""Tests des labels (séparés du flux) et de l'absence de labels dans ``transactions``."""

from __future__ import annotations

import csv
import functools
import json
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from aml.common.schemas import TRANSACTION_FIELDS, validate_message
from aml.simulator.dataset import build_dataset, generate_dataset, write_dataset
from aml.simulator.labels import (
    LABEL_FIELDS,
    LabelError,
    read_labels,
    scenario_report,
    validate_label,
    write_labels,
)
from aml.simulator.normal import CSV_FIELDS, publish_kafka, write_csv
from aml.simulator.scenario_config import LEVELS, SCENARIOS

POPULATION = 1500
CONFIG = {
    "max_account_rate": 1.0,
    "profiles": {"light": {"block_assignment": "any",
                           "cases": {name: {"medium": 1} for name in SCENARIOS}}},
}


@functools.cache
def dataset() -> tuple[Any, ...]:
    return generate_dataset("light", 42, CONFIG, population_size=POPULATION)


def good_label(**changes: str) -> dict[str, str]:
    row = {"account_id": "acct-000001", "tx_id": "", "scenario": "mule", "role": "mule",
           "start_ts": "2027-02-01T10:00:00Z", "end_ts": "2027-02-02T10:00:00Z",
           "case_id": "case-001", "sophistication": "low"}
    return {**row, **changes}


# ------------------------------------------------------------------ forme des labels

def test_label_rows_have_the_documented_columns_and_are_valid() -> None:
    _, labels, _ = dataset()
    assert labels
    for row in labels:
        assert tuple(row) == LABEL_FIELDS
        validate_label(row)


@pytest.mark.parametrize(
    "change",
    [{"scenario": "smurfing"}, {"role": "boss"}, {"sophistication": "extreme"},
     {"case_id": ""}, {"end_ts": "2027-01-01T00:00:00Z"}],
)
def test_invalid_labels_are_rejected(change: dict[str, str]) -> None:
    with pytest.raises(LabelError):
        validate_label(good_label(**change))


def test_label_with_unknown_column_is_rejected() -> None:
    with pytest.raises(LabelError):
        validate_label({**good_label(), "extra": "x"})


def test_account_rows_describe_each_case_and_are_unique() -> None:
    _, labels, manifest = dataset()
    accounts = [row for row in labels if not row["tx_id"]]
    keys = [(r["case_id"], r["account_id"], r["role"], r["tx_id"]) for r in labels]
    assert len(keys) == len(set(keys))
    assert len(accounts) == manifest["rates"]["labeled_accounts"]
    for case in manifest["cases"]:
        rows = [r for r in accounts if r["case_id"] == case["case_id"]]
        assert len(rows) == case["accounts"]
        assert {r["scenario"] for r in rows} == {case["scenario"]}
        assert {r["sophistication"] for r in rows} == {case["sophistication"]}
        assert all(r["start_ts"] <= r["end_ts"] for r in rows)


def test_transaction_rows_point_to_real_scenario_transactions() -> None:
    events, labels, manifest = dataset()
    by_id = {event["tx_id"]: event for event in events}
    account_rows = {(r["case_id"], r["account_id"]): r for r in labels if not r["tx_id"]}
    rows = [r for r in labels if r["tx_id"]]
    assert len(rows) == manifest["rates"]["labeled_transactions"]
    assert len({r["tx_id"] for r in rows}) == len(rows)
    for row in rows:
        event = by_id[row["tx_id"]]
        assert row["start_ts"] == row["end_ts"] == event["timestamp"]
        assert row["account_id"] in {event["source_account_id"], event["target_account_id"]}
        account = account_rows[(row["case_id"], row["account_id"])]
        assert account["role"] == row["role"]
        assert account["start_ts"] <= row["start_ts"] <= account["end_ts"]


def test_camouflage_transactions_are_not_labeled() -> None:
    _, labels, manifest = dataset()
    assert manifest["rates"]["camouflage_transactions"] > 0
    assert len([r for r in labels if r["tx_id"]]) == manifest["rates"]["labeled_transactions"]


def test_rates_are_measured_and_consistent() -> None:
    events, _, manifest = dataset()
    rates = manifest["rates"]
    assert rates["total_transactions"] == len(events)
    assert rates["account_rate"] == round(rates["labeled_accounts"] / POPULATION, 6)
    assert rates["transaction_rate"] == round(rates["labeled_transactions"] / len(events), 6)
    assert {c["scenario"] for c in manifest["cases"]} == set(SCENARIOS)
    assert {c["sophistication"] for c in manifest["cases"]} <= set(LEVELS)
    report = scenario_report(manifest)
    assert report["scenario_counts"]["mule/medium"] == 1
    assert report["suspicious_rate"]["accounts"] == rates["account_rate"]


def test_default_profiles_stay_under_one_percent_of_accounts() -> None:
    # Plan seul (sans générer le flux) : 5 000 clients pour light, 20 000 pour full.
    from aml.simulator.dataset import Dataset

    for profile in ("light", "full"):
        planned = Dataset(profile, 42)
        accounts = {a for case in planned.cases for a in case.draft.roles}
        assert len(accounts) / planned.population_size < 0.01


# ------------------------------------------------ labels absents du flux transactions

def test_events_contain_exactly_the_contract_fields() -> None:
    events, _, _ = dataset()
    for event in events:
        assert set(event) == TRANSACTION_FIELDS
        validate_message("transactions", event)


def test_injecting_a_label_field_into_a_scenario_event_is_rejected() -> None:
    events, labels, _ = dataset()
    event = next(e for e in events if e["tx_id"] == next(r["tx_id"] for r in labels if r["tx_id"]))
    for field in ("scenario", "case_id", "role", "sophistication", "is_suspicious"):
        with pytest.raises(Exception, match="unexpected fields"):
            validate_message("transactions", {**event, field: "x"})


def test_written_files_keep_labels_out_of_the_transaction_csv(tmp_path: Path) -> None:
    transactions, labels, manifest_path = (tmp_path / "tx.csv", tmp_path / "labels" / "l.csv",
                                           tmp_path / "labels" / "l.manifest.json")
    ds = build_dataset("light", 42, CONFIG, population_size=POPULATION)
    manifest = write_dataset(ds, transactions, labels, manifest_path)
    with transactions.open(encoding="utf-8", newline="") as handle:
        assert tuple(next(csv.reader(handle))) == CSV_FIELDS
    text = transactions.read_text(encoding="utf-8")
    for token in (*SCENARIOS, "case-0", "depositor", "originator", "sophistication"):
        assert token not in text
    assert tuple(next(csv.reader(labels.open(encoding="utf-8")))) == LABEL_FIELDS
    assert len(read_labels(labels)) == manifest["rates"]["labeled_accounts"] + manifest[
        "rates"]["labeled_transactions"]
    assert json.loads(manifest_path.read_text(encoding="utf-8"))["seed"] == 42


def test_write_labels_round_trip(tmp_path: Path) -> None:
    assert write_labels([good_label()], tmp_path / "x.csv") == 1
    assert read_labels(tmp_path / "x.csv") == [good_label()]


def test_kafka_messages_for_scenario_transactions_carry_no_label(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Rejoue via le vrai ``publish_kafka`` (producteur simulé) un extrait avec des cas."""
    events, labels, _ = dataset()
    labeled = {r["tx_id"] for r in labels if r["tx_id"]}
    sample = [e for e in events if e["tx_id"] in labeled][:150] + events[:100]
    csv_path = tmp_path / "sample.csv"
    write_csv(sample, csv_path)
    sent: list[tuple[str, str, str]] = []

    class StubProducer:
        def __init__(self, config: dict[str, Any]) -> None:
            self.config = config

        def produce(self, topic: str, key: str, value: str) -> None:
            sent.append((topic, key, value))

        def poll(self, timeout: float) -> int:
            return 0

        def flush(self, timeout: float) -> int:
            return 0

    monkeypatch.setitem(sys.modules, "confluent_kafka", types.SimpleNamespace(Producer=StubProducer))
    assert publish_kafka(csv_path, rate=500, bootstrap_servers="stub:9092") == len(sample)
    assert {topic for topic, _, _ in sent} == {"transactions"}
    scenario_ids = set()
    for _, key, value in sent:
        message = json.loads(value)
        assert set(message) == TRANSACTION_FIELDS
        assert key == message["source_account_id"]
        validate_message("transactions", message)
        scenario_ids.add(message["tx_id"] in labeled)
    assert scenario_ids == {True, False}  # l'extrait mêlait bien scénario et normal
