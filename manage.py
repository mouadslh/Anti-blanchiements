"""Cross-platform project command entry point (Python standard library only)."""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import time
import unittest
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

ROOT = Path(__file__).resolve().parent
TOPICS = ("transactions", "features", "scores", "alerts")


def load_env() -> None:
    """Load simple KEY=VALUE entries so CLI checks share Compose's .env settings."""
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def run(command: list[str], *, check: bool = True, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=ROOT,
        check=check,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
    )


def compose(*args: str, check: bool = True, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return run(["docker", "compose", *args], check=check, capture=capture)


def wait_for_services() -> None:
    deadline = time.monotonic() + 150
    while time.monotonic() < deadline:
        result = compose("ps", "--format", "json", capture=True)
        try:
            services = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
            if len(services) >= 3 and all("healthy" in item.get("Health", "") for item in services):
                return
        except json.JSONDecodeError:
            pass
        time.sleep(3)
    raise RuntimeError("Services did not all become healthy within 150 seconds")


def kafka(*args: str, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return compose("exec", "-T", "kafka", "/opt/kafka/bin/" + args[0], *args[1:], capture=capture)


def phase0_smoke() -> None:
    """Create topics, round-trip a message, and check Grafana's provisioned datasource."""
    for topic in TOPICS:
        kafka("kafka-topics.sh", "--bootstrap-server", "localhost:9092", "--create", "--if-not-exists", "--topic", topic)
    topic = "_phase0_smoke"
    kafka("kafka-topics.sh", "--bootstrap-server", "localhost:9092", "--create", "--if-not-exists", "--topic", topic)
    marker = "phase0-smoke-ok"
    producer = ["docker", "compose", "exec", "-T", "kafka", "/opt/kafka/bin/kafka-console-producer.sh", "--bootstrap-server", "localhost:9092", "--topic", topic]
    subprocess.run(producer, cwd=ROOT, input=marker + "\n", text=True, check=True, stdout=subprocess.DEVNULL)
    consumer = kafka("kafka-console-consumer.sh", "--bootstrap-server", "localhost:9092", "--topic", topic,
                     "--from-beginning", "--max-messages", "1", "--timeout-ms", "15000", capture=True)
    if marker not in consumer.stdout:
        raise RuntimeError("Kafka smoke message was not consumed")
    print("Kafka topic creation and publish/consume: PASS")
    request = urllib.request.Request("http://localhost:3000/api/datasources", headers={
        "Authorization": "Basic " + base64.b64encode(
            ("admin:" + os.environ.get("GRAFANA_ADMIN_PASSWORD", "admin_local_dev")).encode()
        ).decode()
    })
    with urllib.request.urlopen(request, timeout=10) as response:
        datasources = json.loads(response.read())
    datasource = next(
        (item for item in datasources if item.get("uid") == "aml-postgres"), None
    )
    if not datasource:
        raise RuntimeError("Grafana is healthy but has no provisioned PostgreSQL datasource")
    health_request = urllib.request.Request(
        "http://localhost:3000/api/datasources/uid/aml-postgres/health",
        headers=request.headers,
    )
    with urllib.request.urlopen(health_request, timeout=10) as response:
        health = json.loads(response.read())
    if health.get("status") != "OK":
        raise RuntimeError(f"Grafana PostgreSQL datasource check failed: {health}")
    print("Grafana PostgreSQL datasource provisioned: PASS")
    print(f"Grafana to PostgreSQL connection: {health['message']}")


def main() -> int:
    load_env()
    parser = argparse.ArgumentParser(description="AML project command line")
    parser.add_argument("command", choices=("up", "down", "simulate", "train", "evaluate", "test", "reset"))
    parser.add_argument("--report", action="store_true", help="Print a simulation statistics report")
    parser.add_argument("--profile", choices=("light", "full"), default="light", help="Simulation population profile")
    parser.add_argument("--seed", type=int, default=42, help="Deterministic random seed")
    parser.add_argument("--output", type=Path, help="CSV output path (default: data/transactions/normal-<profile>-seed<seed>.csv)")
    parser.add_argument("--replay", action="store_true", help="Replay the generated CSV to Kafka")
    parser.add_argument("--store-raw", action="store_true", help="Idempotently store generated events in PostgreSQL")
    parser.add_argument("--rate", type=int, default=100, help="Kafka replay rate, 1 to 500 events/second")
    parser.add_argument("--duration", type=float, help="Stop Kafka replay after this many seconds")
    args = parser.parse_args()
    try:
        if args.command == "up":
            compose("up", "-d")
            wait_for_services()
            phase0_smoke()
            postgres_port = os.environ.get("POSTGRES_PORT", "5433")
            print(f"Stack is ready: Grafana http://localhost:3000; PostgreSQL localhost:{postgres_port}; Kafka localhost:9092")
        elif args.command == "down":
            compose("down")
        elif args.command == "reset":
            compose("down", "-v")
        elif args.command == "test":
            suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
            result = unittest.TextTestRunner(verbosity=2).run(suite)
            return 0 if result.wasSuccessful() else 1
        elif args.command == "simulate":
            from aml.simulator.normal import (
                generate_transactions,
                publish_kafka,
                report_json,
                store_postgres,
                summarize_csv,
                write_csv,
            )

            output = args.output or ROOT / "data" / "transactions" / f"normal-{args.profile}-seed{args.seed}.csv"
            count = write_csv(generate_transactions(profile=args.profile, seed=args.seed), output)
            print(f"{count} transaction(s) normales écrites dans {output}")
            if args.report:
                print(report_json(summarize_csv(output)))
            if args.replay:
                bootstrap_servers = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
                sent = publish_kafka(output, rate=args.rate, bootstrap_servers=bootstrap_servers,
                                     duration=args.duration)
                print(f"{sent} transaction(s) publiées dans Kafka:transactions")
            if args.store_raw:
                dsn = os.environ.get("DATABASE_URL") or (
                    f"host={os.environ.get('POSTGRES_HOST', 'localhost')} "
                    f"port={os.environ.get('POSTGRES_PORT', '5433')} "
                    f"dbname={os.environ.get('POSTGRES_DB', 'aml')} "
                    f"user={os.environ.get('POSTGRES_USER', 'aml')} "
                    f"password={os.environ.get('POSTGRES_PASSWORD', 'aml_local_dev')}"
                )
                inserted = store_postgres(output, dsn=dsn)
                print(f"{inserted} transaction(s) brutes insérées (les tx_id déjà présents sont ignorés)")
        else:
            print(f"'{args.command}' is a Phase 0 skeleton; implemented in its scheduled phase.", file=sys.stderr)
            return 2
    except (subprocess.CalledProcessError, RuntimeError, OSError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
