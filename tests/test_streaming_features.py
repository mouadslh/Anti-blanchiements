from datetime import UTC, datetime, timedelta

import pytest

from aml.streaming.features import (
    AccountEvent,
    FeatureConfig,
    as_feature_message,
    calculate_features,
    transaction_to_account_events,
)


def event(tx_id, at, *, amount=100, flow="out", channel="transfer", side="source", cp="acct-000002"):
    return AccountEvent(
        account_id="acct-000001", tx_id=tx_id,
        timestamp=datetime.fromisoformat(at).replace(tzinfo=UTC), side=side,
        amount=amount, channel=channel, counterparty=cp, city="Casablanca", flow=flow,
    )


def test_windows_ratios_threshold_cash_and_delay_are_hand_calculated():
    base = datetime(2026, 1, 1, tzinfo=UTC)
    history = [
        event("a", (base - timedelta(hours=2)).isoformat(), amount=500, flow="in", channel="cash_deposit", side="target", cp="acct-000003"),
        event("b", (base - timedelta(minutes=30)).isoformat(), amount=900, flow="in", side="target", cp="acct-000004"),
        event("c", (base - timedelta(minutes=10)).isoformat(), amount=700, flow="in", side="target", cp="acct-000005"),
    ]
    current = event("d", base.isoformat(), amount=950, flow="out", side="source", cp="acct-000006")
    features = calculate_features(history, current, FeatureConfig(1000, 30, 3))

    assert features["tx_count_1h"] == 3
    assert features["total_amount_1h_mad"] == 2550
    assert features["tx_count_24h"] == 4
    assert features["tx_count_7d"] == 4
    assert features["distinct_counterparties_24h"] == 4
    assert features["amount_to_avg_ratio"] == 1.357143  # 950 / mean(500, 900, 700)
    assert features["near_threshold_share_24h"] == 0.5
    assert features["cash_share_24h"] == 0.25
    assert features["inflow_outflow_ratio_24h"] == pytest.approx(2100 / 950)
    assert features["avg_in_to_out_delay_s_24h"] == 600  # nearest inbound was at -10m


def test_future_event_does_not_leak_and_message_has_stable_contract():
    base = datetime(2026, 1, 1, tzinfo=UTC)
    current = event("a", base.isoformat(), amount=200)
    future = event("z", (base + timedelta(minutes=1)).isoformat(), amount=1)
    features = calculate_features([future], current, FeatureConfig(1000, 30, 1))
    assert features["tx_count_1h"] == 1
    assert features["amount_to_avg_ratio"] is None
    message = as_feature_message(current, features)
    assert set(message) == {"account_id", "tx_id", "side", "as_of", "feature_version", "features"}
    assert message["as_of"].endswith("Z")


def test_transaction_expands_internal_counterparty_and_cash_flow():
    tx = {
        "tx_id": "t-1", "timestamp": "2026-01-01T00:00:00Z",
        "source_account_id": "acct-000001", "target_account_id": "acct-000002",
        "amount": 50, "currency": "MAD", "channel": "cash_deposit",
        "source_customer_type": "student", "city": "Rabat",
    }
    source, target = transaction_to_account_events(tx)
    assert (source.flow, source.side, target.flow, target.side) == ("in", "source", "in", "target")
    assert source.counterparty == "acct-000002"


@pytest.mark.integration
def test_checkpoint_restart_reprocesses_no_rows(tmp_path):
    """Exercise Spark's real file source, state store and durable checkpoint on restart."""
    pytest.importorskip("pyspark")
    pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")
    import json
    import os

    from pyspark.sql import SparkSession
    from pyspark.sql.types import StringType, StructField, StructType
    from aml.streaming.feature_job import expand_account_events, parse_transactions, stateful_features

    os.environ.setdefault("SPARK_LOCAL_IP", "127.0.0.1")
    spark = (SparkSession.builder.master("local[2]").appName("checkpoint-restart-test")
             .config("spark.ui.enabled", "false").config("spark.sql.shuffle.partitions", "2")
             .config("spark.sql.session.timeZone", "UTC").getOrCreate())
    spark.sparkContext.setLogLevel("ERROR")
    source, checkpoint, output = (tmp_path / "source", tmp_path / "checkpoint", tmp_path / "output")
    source.mkdir()
    schema = StructType([StructField("value", StringType(), True)])
    config = {"reporting_threshold_mad": 1000, "history_days": 30, "min_history_events": 1,
              "watermark_delay": "2 hours"}

    def write_transaction(name, tx_id, timestamp):
        tx = {"tx_id": tx_id, "timestamp": timestamp, "source_account_id": "acct-000001",
              "target_account_id": "ext-cash", "amount": 100, "currency": "MAD",
              "channel": "cash_withdrawal", "source_customer_type": "student", "city": "Rabat"}
        (source / name).write_text(json.dumps({"value": json.dumps(tx)}) + "\n", encoding="utf-8")

    def start_query():
        raw = spark.readStream.schema(schema).json(str(source))
        events = expand_account_events(parse_transactions(raw, "2 hours"))
        features = stateful_features(events, config)
        return (features.writeStream.format("parquet").outputMode("append")
                .option("path", str(output)).option("checkpointLocation", str(checkpoint))
                .trigger(processingTime="1 second").start())

    try:
        write_transaction("part-1.json", "restart-1", "2026-01-01T00:00:00Z")
        query = start_query()
        query.processAllAvailable()
        query.stop()
        query.awaitTermination(15)
        write_transaction("part-2.json", "restart-2", "2026-01-01T00:01:00Z")
        query = start_query()
        query.processAllAvailable()
        query.stop()
        rows = spark.read.parquet(str(output)).select("tx_id", "features_json").collect()
        tx_ids = [row.tx_id for row in rows]
        assert sorted(tx_ids) == ["restart-1", "restart-2"]
        assert len(tx_ids) == len(set(tx_ids))
        second = next(row for row in rows if row.tx_id == "restart-2")
        assert json.loads(second.features_json)["tx_count_1h"] == 2
    finally:
        spark.stop()
