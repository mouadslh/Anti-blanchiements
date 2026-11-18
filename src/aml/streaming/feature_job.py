"""Spark Structured Streaming job: Kafka transactions -> account features -> Kafka/PostgreSQL."""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from aml.streaming.features import (
    AccountEvent,
    FeatureConfig,
    as_feature_message,
    calculate_features,
    event_from_state,
    event_state_dict,
)

LOG = logging.getLogger("aml.streaming.features")
TRANSACTION_FIELDS = {
    "tx_id", "timestamp", "source_account_id", "target_account_id", "amount", "currency",
    "channel", "source_customer_type", "city",
}
ACCOUNT_ID_PATTERN = r"^acct-[0-9]{6}$"
COUNTERPARTY_ID_PATTERN = r"^(acct-[0-9]{6}|ext-[A-Za-z0-9-]+)$"


def _spark_types() -> tuple[Any, Any, Any, Any]:
    try:
        from pyspark.sql import functions as F
        from pyspark.sql.types import (
            DoubleType,
            MapType,
            StringType,
            StructField,
            StructType,
            TimestampType,
        )
    except ImportError as exc:
        raise RuntimeError("Spark indisponible; installez `pip install -e '.[streaming]'`.") from exc
    return F, (DoubleType, MapType, StringType, StructField, StructType, TimestampType), None, None


def _duration_seconds(value: str) -> int:
    match = re.fullmatch(r"\s*(\d+)\s+(second|minute|hour|day)s?\s*", value.lower())
    if not match:
        raise ValueError(f"Invalid duration {value!r}; use e.g. '2 hours' or '30 minutes'")
    amount = int(match.group(1))
    multiplier = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}[match.group(2)]
    if amount <= 0:
        raise ValueError("duration must be positive")
    return amount * multiplier


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    config_path = Path(path or os.environ.get("AML_STREAMING_CONFIG", "config/streaming.json"))
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["source_topic"] = os.environ.get(
        "AML_STREAMING_SOURCE_TOPIC", config["source_topic"]
    )
    config["features_topic"] = os.environ.get(
        "AML_STREAMING_FEATURES_TOPIC", config["features_topic"]
    )
    config["checkpoint_location"] = os.environ.get(
        "AML_STREAMING_CHECKPOINT_LOCATION", config["checkpoint_location"]
    )
    config["bootstrap_servers"] = os.environ.get(
        "AML_STREAMING_BOOTSTRAP_SERVERS", config["bootstrap_servers"]
    )
    config["postgres_password"] = os.environ.get(
        "POSTGRES_PASSWORD", config.get("postgres_password", "")
    )
    config["postgres_db"] = os.environ.get("POSTGRES_DB", config.get("postgres_db", "aml"))
    config["postgres_user"] = os.environ.get("POSTGRES_USER", config.get("postgres_user", "aml"))
    required = {
        "bootstrap_servers", "source_topic", "features_topic", "starting_offsets",
        "max_offsets_per_trigger", "trigger_interval", "watermark_delay",
        "reporting_threshold_mad", "history_days", "min_history_events",
        "checkpoint_location", "postgres_table", "postgres_host", "postgres_port",
        "postgres_db", "postgres_user", "postgres_password", "spark_local_cores",
        "shuffle_partitions",
    }
    missing = required - config.keys()
    if missing:
        raise ValueError(f"streaming configuration missing: {', '.join(sorted(missing))}")
    if config["starting_offsets"] not in {"earliest", "latest"}:
        raise ValueError("starting_offsets must be 'earliest' or 'latest'")
    if int(config["max_offsets_per_trigger"]) < 1:
        raise ValueError("max_offsets_per_trigger must be positive")
    if int(config["spark_local_cores"]) != 2:
        raise ValueError("the project Spark resource limit is local[2]")
    _duration_seconds(config["watermark_delay"])
    _duration_seconds(config["trigger_interval"])
    FeatureConfig(
        float(config["reporting_threshold_mad"]),
        int(config["history_days"]),
        int(config["min_history_events"]),
    )
    if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", config["postgres_table"]):
        raise ValueError("postgres_table must be a simple SQL identifier")
    return config


def _postgres_dsn(config: dict[str, Any]) -> str:
    return (
        f"host={config['postgres_host']} port={config['postgres_port']} "
        f"dbname={config['postgres_db']} user={config['postgres_user']} "
        f"password={config['postgres_password']}"
    )


def ensure_features_table(config: dict[str, Any]) -> None:
    """Create the streaming table idempotently; do not alter the shared proposal DDL."""
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("psycopg indisponible dans le worker Spark") from exc
    table = config["postgres_table"]
    with psycopg.connect(_postgres_dsn(config)) as connection:
        connection.execute(
            f"""CREATE TABLE IF NOT EXISTS {table} (
                account_id TEXT NOT NULL,
                tx_id TEXT NOT NULL,
                side TEXT NOT NULL CHECK (side IN ('source', 'target')),
                as_of TIMESTAMPTZ NOT NULL,
                feature_version TEXT NOT NULL,
                features JSONB NOT NULL,
                batch_id BIGINT NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY (account_id, tx_id)
            )"""
        )


def parse_transactions(stream: Any, watermark_delay: str) -> Any:
    """Parse only the exact v1 transaction keys, deduplicate IDs, and set event-time watermark."""
    F, spark_types, _, _ = _spark_types()
    DoubleType, MapType, StringType, StructField, StructType, _ = spark_types
    schema = StructType(
        [
            StructField("tx_id", StringType(), True),
            StructField("timestamp", StringType(), True),
            StructField("source_account_id", StringType(), True),
            StructField("target_account_id", StringType(), True),
            StructField("amount", DoubleType(), True),
            StructField("currency", StringType(), True),
            StructField("channel", StringType(), True),
            StructField("source_customer_type", StringType(), True),
            StructField("city", StringType(), True),
        ]
    )
    expected_keys = F.array(*[F.lit(key) for key in sorted(TRANSACTION_FIELDS)])
    raw = stream.select(F.col("value").cast("string").alias("raw_value"))
    mapped = raw.withColumn("raw_object", F.from_json("raw_value", MapType(StringType(), StringType())))
    exact_contract = F.array_sort(F.map_keys("raw_object")) == expected_keys
    typed = mapped.where(exact_contract).select(F.from_json("raw_value", schema).alias("tx"))
    selected = typed.select(
        F.col("tx.tx_id").alias("tx_id"),
        F.to_timestamp("tx.timestamp").alias("event_ts"),
        F.col("tx.source_account_id").alias("source_account_id"),
        F.col("tx.target_account_id").alias("target_account_id"),
        F.col("tx.amount").alias("amount"),
        F.col("tx.currency").alias("currency"),
        F.col("tx.channel").alias("channel"),
        F.col("tx.source_customer_type").alias("source_customer_type"),
        F.col("tx.city").alias("city"),
    )
    valid = selected.where(
        F.col("tx_id").isNotNull()
        & (F.length(F.trim("tx_id")) > 0)
        & F.col("event_ts").isNotNull()
        & F.col("source_account_id").rlike(ACCOUNT_ID_PATTERN)
        & F.col("target_account_id").rlike(COUNTERPARTY_ID_PATTERN)
        & (F.col("amount") > 0)
        & ~F.isnan("amount")
        & (F.abs(F.col("amount")) < float("inf"))
        & (F.col("currency") == "MAD")
        & F.col("channel").isin(
            "cash_deposit", "cash_withdrawal", "transfer", "card", "international_transfer"
        )
        & F.col("source_customer_type").isin("salaried", "student", "merchant", "company")
        & F.col("city").isNotNull()
        & (F.length(F.trim("city")) > 0)
        & (F.col("source_account_id") != F.col("target_account_id"))
    )
    watermarked = valid.withWatermark("event_ts", watermark_delay)
    return watermarked.dropDuplicatesWithinWatermark(["tx_id"])


def expand_account_events(transactions: Any) -> Any:
    F, _, _, _ = _spark_types()
    source = F.struct(
        F.col("source_account_id").alias("account_id"),
        F.col("tx_id"), F.col("event_ts"), F.lit("source").alias("side"), F.col("amount"),
        F.col("channel"), F.col("target_account_id").alias("counterparty"), F.col("city"),
        F.when(F.col("channel") == "cash_deposit", F.lit("in"))
        .otherwise(F.lit("out")).alias("flow"),
    )
    target = F.struct(
        F.col("target_account_id").alias("account_id"),
        F.col("tx_id"), F.col("event_ts"), F.lit("target").alias("side"), F.col("amount"),
        F.col("channel"), F.col("source_account_id").alias("counterparty"), F.col("city"),
        F.lit("in").alias("flow"),
    )
    records = F.when(
        F.col("target_account_id").rlike(ACCOUNT_ID_PATTERN), F.array(source, target)
    ).otherwise(F.array(source))
    return transactions.select(F.explode(records).alias("event")).select("event.*")


def stateful_features(account_events: Any, config: dict[str, Any]) -> Any:
    """Run the per-account event-time state machine with persistent Spark state."""
    try:
        import pandas as pd
        from pyspark.sql.streaming.state import GroupStateTimeout
        from pyspark.sql.types import StringType, StructField, StructType, TimestampType
    except ImportError as exc:
        raise RuntimeError("Spark/Pandas state dependencies are unavailable") from exc

    feature_config = FeatureConfig(
        float(config["reporting_threshold_mad"]),
        int(config["history_days"]),
        int(config["min_history_events"]),
    )
    output_schema = StructType(
        [
            StructField("account_id", StringType(), False),
            StructField("tx_id", StringType(), False),
            StructField("side", StringType(), False),
            StructField("as_of", TimestampType(), False),
            StructField("feature_version", StringType(), False),
            StructField("features_json", StringType(), False),
        ]
    )
    state_schema = StructType([StructField("history_json", StringType(), False)])
    retain_seconds = int(config["history_days"]) * 86400
    watermark_seconds = _duration_seconds(config["watermark_delay"])

    def update_account(
        key: tuple[str], batches: Iterator[pd.DataFrame], state: Any
    ) -> Iterator[pd.DataFrame]:
        if state.hasTimedOut:
            state.remove()
            return iter(())
        history = [event_from_state(item) for item in json.loads(state.get[0])] if state.exists else []
        frames = list(batches)
        if not frames:
            return iter(())
        batch = pd.concat(frames, ignore_index=True).sort_values(
            ["event_ts", "tx_id", "side"], kind="stable"
        )
        emitted: list[dict[str, Any]] = []
        latest: datetime | None = None
        for row in batch.to_dict("records"):
            timestamp = row["event_ts"]
            if hasattr(timestamp, "to_pydatetime"):
                timestamp = timestamp.to_pydatetime()
            # Spark TimestampType is delivered as a naive Python datetime in UTC.
            if timestamp.tzinfo is None:
                from datetime import UTC
                timestamp = timestamp.replace(tzinfo=UTC)
            current = AccountEvent(
                account_id=str(row["account_id"]),
                tx_id=str(row["tx_id"]),
                timestamp=timestamp,
                side=str(row["side"]),
                amount=float(row["amount"]),
                channel=str(row["channel"]),
                counterparty=str(row["counterparty"]),
                city=str(row["city"]),
                flow=str(row["flow"]),
            )
            features = calculate_features(history, current, feature_config)
            message = as_feature_message(current, features)
            emitted.append(
                {
                    "account_id": message["account_id"], "tx_id": message["tx_id"],
                    "side": message["side"], "as_of": current.timestamp.replace(tzinfo=None),
                    "feature_version": message["feature_version"],
                    "features_json": json.dumps(features, sort_keys=True, separators=(",", ":")),
                }
            )
            history.append(current)
            latest = current.timestamp if latest is None else max(latest, current.timestamp)
            # Retain an extra watermark interval so an accepted late event still
            # sees the complete historical baseline.
            expiry = latest - timedelta(
                days=config["history_days"], seconds=watermark_seconds
            )
            history = [event for event in history if event.timestamp > expiry]
        if latest is not None:
            state.update((json.dumps([event_state_dict(event) for event in history], separators=(",", ":")),))
            timeout_at = latest + timedelta(seconds=retain_seconds + watermark_seconds)
            state.setTimeoutTimestamp(int(timeout_at.timestamp() * 1000))
        return iter([pd.DataFrame(emitted)])

    return account_events.groupBy("account_id").applyInPandasWithState(
        update_account,
        outputStructType=output_schema,
        stateStructType=state_schema,
        outputMode="Append",
        timeoutConf=GroupStateTimeout.EventTimeTimeout,
    )


def _write_postgres_partition(rows: Iterator[Any], dsn: str, table: str, batch_id: int) -> None:
    import psycopg

    with psycopg.connect(dsn) as connection, connection.cursor() as cursor:
        statement = f"""INSERT INTO {table}
            (account_id, tx_id, side, as_of, feature_version, features, batch_id)
            VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s)
            ON CONFLICT (account_id, tx_id) DO UPDATE SET
              side = EXCLUDED.side, as_of = EXCLUDED.as_of,
              feature_version = EXCLUDED.feature_version, features = EXCLUDED.features,
              batch_id = EXCLUDED.batch_id, updated_at = now()"""
        cursor.executemany(
            statement,
            [
                (
                    row["account_id"], row["tx_id"], row["side"], row["as_of"],
                    row["feature_version"], row["features_json"], batch_id,
                )
                for row in rows
            ],
        )


def write_feature_batch(batch: Any, batch_id: int, config: dict[str, Any]) -> None:
    """Idempotent PostgreSQL materialization plus keyed Kafka feature messages."""
    if batch.isEmpty():
        return
    dsn = _postgres_dsn(config)
    table = config["postgres_table"]
    batch.foreachPartition(
        lambda rows: _write_postgres_partition(rows, dsn, table, batch_id)
    )
    kafka_records = batch.selectExpr(
        "CAST(account_id AS STRING) AS key",
        "to_json(named_struct('account_id', account_id, 'tx_id', tx_id, 'side', side, "
        "'as_of', date_format(as_of, \"yyyy-MM-dd'T'HH:mm:ss'Z'\"), "
        "'feature_version', feature_version, 'features', from_json(features_json, "
        "'MAP<STRING, DOUBLE>'))) AS value",
    )
    (kafka_records.write.format("kafka")
     .option("kafka.bootstrap.servers", config["bootstrap_servers"])
     .option("topic", config["features_topic"])
     .save())
    LOG.info("batch=%s feature_rows=%s", batch_id, batch.count())


def _log_progress(query: Any, stop: threading.Event) -> None:
    previous_input = 0.0
    previous_batch = 0
    while not stop.wait(5):
        progress = query.lastProgress
        if not progress:
            continue
        durations = progress.get("durationMs", {})
        state_operators = progress.get("stateOperators", [])
        late_dropped = sum(
            int(operator.get("numRowsDroppedByWatermark", 0))
            for operator in state_operators
        )
        LOG.info(
            "stream_metrics batch=%s input_rps=%.1f processed_rps=%.1f add_batch_ms=%s "
            "watermark=%s late_dropped_rows=%s",
            progress.get("batchId"), progress.get("inputRowsPerSecond", previous_input),
            progress.get("processedRowsPerSecond", previous_input), durations.get("addBatch"),
            progress.get("eventTime", {}).get("watermark"), late_dropped,
        )
        previous_input = float(progress.get("inputRowsPerSecond", previous_input))
        previous_batch = int(progress.get("batchId", previous_batch))
    LOG.debug("last reported batch=%s", previous_batch)


def run_job(config: dict[str, Any] | None = None) -> None:
    """Start and await the checkpointed Kafka-to-features query."""
    from pyspark.sql import SparkSession

    config = config or load_config()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    ensure_features_table(config)
    spark = (
        SparkSession.builder.appName("aml-account-features-v1")
        .master(f"local[{config['spark_local_cores']}]")
        .config("spark.sql.shuffle.partitions", str(config["shuffle_partitions"]))
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.streaming.metricsEnabled", "true")
        .getOrCreate()
    )
    kafka_input = (
        spark.readStream.format("kafka")
        .option("kafka.bootstrap.servers", config["bootstrap_servers"])
        .option("subscribe", config["source_topic"])
        .option("startingOffsets", config["starting_offsets"])
        .option("maxOffsetsPerTrigger", str(config["max_offsets_per_trigger"]))
        .option("failOnDataLoss", "true")
        .load()
    )
    transactions = parse_transactions(kafka_input, config["watermark_delay"])
    account_events = expand_account_events(transactions)
    output = stateful_features(account_events, config)
    query = (
        output.writeStream.outputMode("append")
        .option("checkpointLocation", config["checkpoint_location"])
        .trigger(processingTime=config["trigger_interval"])
        .foreachBatch(lambda batch, batch_id: write_feature_batch(batch, batch_id, config))
        .start()
    )
    stop = threading.Event()
    reporter = threading.Thread(target=_log_progress, args=(query, stop), daemon=True)
    reporter.start()
    LOG.info(
        "started query=%s source=%s output=%s checkpoint=%s watermark=%s",
        query.id, config["source_topic"], config["features_topic"],
        config["checkpoint_location"], config["watermark_delay"],
    )
    try:
        query.awaitTermination()
    finally:
        stop.set()
        reporter.join(timeout=2)
        spark.stop()


if __name__ == "__main__":
    run_job()
