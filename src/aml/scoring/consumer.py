"""Kafka inference worker for phase-4 base models (no label/database access)."""

from __future__ import annotations

import json
import logging
import os
import time
from functools import partial
from pathlib import Path
from typing import Any

from aml.common.schemas import validate_alert, validate_score
from aml.scoring.models import load_config, score_one_feature_message

LOG = logging.getLogger("aml.scoring.consumer")


def _delivery_error(errors: list[str], error: Any, _message: Any) -> None:
    if error is not None:
        errors.append(str(error))


def score_payload(payload: dict[str, Any], bundle: dict[str, Any], model_name: str) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Build contract-v1 score and optional alert messages from one C-06 feature record."""
    score, fired_rules, top_features = score_one_feature_message(
        payload["features"], bundle, model_name
    )
    message = {
        "account_id": payload["account_id"],
        "tx_id": payload["tx_id"],
        "risk_score": float(score),
        "model_versions": {model_name: str(bundle["version"])},
        "ts": payload["as_of"],
    }
    validate_score(message)
    threshold = float(bundle["thresholds"][model_name])
    alert = None
    if score >= threshold:
        alert = {
            **message,
            "explanation": {
                "model": model_name,
                "threshold": threshold,
                "fired_rules": fired_rules,
                "top_features": top_features,
                "message_fr": (
                    f"Score {model_name} de {score:.3f}, supérieur ou égal au seuil "
                    f"calibré {threshold:.3f}. Vérifier les opérations récentes du compte."
                ),
            },
        }
        validate_alert(alert)
    return message, alert


def run_consumer(config: dict[str, Any] | None = None) -> None:
    try:
        import joblib
        from confluent_kafka import Consumer, KafkaError, Producer
    except ImportError as exc:
        raise RuntimeError("Installez les extras `streaming` et `ml` pour lancer le scorer.") from exc

    config = config or load_config(
        os.environ.get("AML_SCORING_CONFIG", "config/scoring_baselines.yaml")
    )
    streaming = config["streaming"]
    model_name = streaming["operating_model"]
    seed = int(streaming["model_seed"])
    bundle_path = Path(config["artifact_dir"]) / f"aml_seed_{seed}.joblib"
    if not bundle_path.exists():
        raise FileNotFoundError(
            f"Modèle absent: {bundle_path}; lancer `python manage.py train-scoring` d'abord"
        )
    bundle = joblib.load(bundle_path)
    consumer = Consumer(
        {
            "bootstrap.servers": streaming["bootstrap_servers"],
            "group.id": streaming["consumer_group"],
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
        }
    )
    producer = Producer({"bootstrap.servers": streaming["bootstrap_servers"], "enable.idempotence": True})
    consumer.subscribe([streaming["input_topic"]])
    LOG.info(
        "started input=%s scores=%s alerts=%s model=%s seed=%s threshold=%.6f",
        streaming["input_topic"], streaming["scores_topic"], streaming["alerts_topic"],
        model_name, seed, bundle["thresholds"][model_name],
    )
    try:
        while True:
            record = consumer.poll(float(streaming["poll_seconds"]))
            if record is None:
                producer.poll(0)
                continue
            if record.error():
                if record.error().code() == KafkaError._PARTITION_EOF:
                    continue
                raise RuntimeError(record.error())
            payload = json.loads(record.value().decode("utf-8"))
            if not isinstance(payload, dict) or not isinstance(payload.get("features"), dict):
                raise TypeError("invalid features message: expected C-06 object with features map")
            score, alert = score_payload(payload, bundle, model_name)
            key = f"{score['account_id']}:{score['tx_id']}".encode()
            callback_errors: list[str] = []

            producer.produce(
                streaming["scores_topic"], key=key,
                value=json.dumps(score, separators=(",", ":")).encode(),
                callback=partial(_delivery_error, callback_errors),
            )
            if alert is not None:
                producer.produce(
                    streaming["alerts_topic"], key=key,
                    value=json.dumps(alert, separators=(",", ":")).encode(),
                    callback=partial(_delivery_error, callback_errors),
                )
            remaining = producer.flush(30)
            if callback_errors:
                raise RuntimeError(f"Kafka output delivery failed: {callback_errors}")
            if remaining:
                raise TimeoutError(f"{remaining} Kafka output messages were not delivered")
            consumer.commit(message=record, asynchronous=False)
            timestamp_type, published_at_ms = record.timestamp()
            publish_to_score_s = (
                max(0.0, time.time() - published_at_ms / 1000)
                if timestamp_type >= 0 and published_at_ms is not None
                else None
            )
            LOG.info(
                "scored account=%s tx=%s score=%.5f alert=%s publish_to_score_s=%s",
                score["account_id"], score["tx_id"], score["risk_score"], alert is not None,
                publish_to_score_s,
            )
    finally:
        consumer.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    run_consumer()
