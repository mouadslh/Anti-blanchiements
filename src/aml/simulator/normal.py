"""Generate normal synthetic transactions without scenario injection or labels.

The simulator implements the current, still-proposed v1 transaction contract and
the default population assumptions in ``docs/simulator_assumptions.md``.
"""

from __future__ import annotations

import bisect
import csv
import itertools
import heapq
import json
import math
import random
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Iterator

from aml.common.schemas import validate_transaction

START = datetime(2027, 1, 15, tzinfo=UTC)
DAYS = 90
PROFILES: dict[str, dict[str, Any]] = {
    "salaried": {"share": .55, "mean": 62, "median": 400, "sigma": 1.0,
                 "network": 8, "channels": {"transfer": .35, "card": .50,
                 "cash_withdrawal": .10, "cash_deposit": .02, "international_transfer": .03}},
    "student": {"share": .15, "mean": 40, "median": 150, "sigma": .8,
                 "network": 5, "channels": {"transfer": .25, "card": .60,
                 "cash_withdrawal": .12, "cash_deposit": .02, "international_transfer": .01}},
    "merchant": {"share": .18, "mean": 140, "median": 1200, "sigma": 1.1,
                 "network": 25, "channels": {"transfer": .20, "card": .15,
                 "cash_withdrawal": .10, "cash_deposit": .50, "international_transfer": .05}},
    "company": {"share": .12, "mean": 120, "median": 15000, "sigma": 1.3,
                 "network": 40, "channels": {"transfer": .70, "card": .10,
                 "cash_withdrawal": .03, "cash_deposit": .05, "international_transfer": .12}},
}
CITIES = (("Casablanca", .28), ("Rabat", .15), ("Marrakech", .12), ("Fes", .10),
          ("Tangier", .10), ("Agadir", .08), ("Meknes", .07), ("Oujda", .05), ("Autre", .05))
CSV_FIELDS = ("tx_id", "timestamp", "source_account_id", "target_account_id", "amount",
              "currency", "channel", "source_customer_type", "city")


@dataclass(frozen=True)
class Customer:
    account_id: str
    profile: str
    city: str
    counterparties: tuple[str, ...]


def _poisson(rng: random.Random, mean: float) -> int:
    """Knuth sampler; profile means remain small enough for this method."""
    limit = math.exp(-mean)
    product = 1.0
    count = 0
    while product > limit:
        count += 1
        product *= rng.random()
    return count - 1


def _weighted_choice(rng: random.Random, values: Iterable[tuple[Any, float]]) -> Any:
    items = tuple(values)
    return rng.choices([item[0] for item in items], weights=[item[1] for item in items], k=1)[0]


def _population(count: int, seed: int) -> list[Customer]:
    rng = random.Random(seed)
    profile_counts = {name: int(count * profile["share"]) for name, profile in PROFILES.items()}
    # Assign rounding leftovers by largest fractional remainder for exact totals.
    for name in sorted(PROFILES, key=lambda key: count * PROFILES[key]["share"] - profile_counts[key], reverse=True)[:count - sum(profile_counts.values())]:
        profile_counts[name] += 1
    types = [name for name, size in profile_counts.items() for _ in range(size)]
    rng.shuffle(types)
    all_ids = [f"acct-{index:06d}" for index in range(1, count + 1)]
    external_ids = [f"ext-{index:06d}" for index in range(1, max(1, math.ceil(count * .2)) + 1)]
    counterparties = all_ids + external_ids
    customers: list[Customer] = []
    for account_id, profile in zip(all_ids, types, strict=True):
        home = _weighted_choice(rng, CITIES)
        options = [value for value in counterparties if value != account_id]
        network = rng.sample(options, min(PROFILES[profile]["network"], len(options)))
        customers.append(Customer(account_id, profile, home, tuple(network)))
    return customers


@lru_cache(maxsize=None)
def _day_cdf(profile: str, channel: str) -> tuple[tuple[float, ...], float]:
    """Cached day-weight cumulative distribution for each profile/channel."""
    day_weights: list[float] = []
    for day in range(DAYS):
        current = START + timedelta(days=day)
        weight = 1.0
        if current.weekday() >= 5:
            weight *= 1.3 if profile in {"salaried", "student"} and channel == "card" else 1.0
            if profile == "company" and channel in {"transfer", "international_transfer"}:
                weight *= .15
        if profile == "merchant" and channel == "cash_deposit" and current.weekday() in {0, 5}:
            weight *= 1.5
        # The dates are simulation hypotheses, not a claim about an official calendar.
        if current.day >= 25 and profile == "salaried" and channel in {"card", "cash_withdrawal"}:
            weight *= 1.15
        if datetime(2027, 2, 8, tzinfo=UTC).date() <= current.date() <= datetime(2027, 3, 8, tzinfo=UTC).date():
            if channel in {"card", "cash_withdrawal"}:
                weight *= 1.05
        if current.date() in {datetime(2027, 3, 9, tzinfo=UTC).date(), datetime(2027, 3, 10, tzinfo=UTC).date()}:
            weight *= .5
        day_weights.append(weight)
    return tuple(itertools.accumulate(day_weights)), sum(day_weights)


def _event_time(rng: random.Random, profile: str, channel: str) -> datetime:
    cumulative, total = _day_cdf(profile, channel)
    day = bisect.bisect_left(cumulative, rng.random() * total)
    current = START + timedelta(days=day)
    if profile == "company" and channel in {"transfer", "international_transfer"} and current.weekday() < 5:
        hour = rng.randrange(9, 17)
    else:
        hour, hour_range = _weighted_choice(
            rng, (((0, 6), .02), ((6, 12), .28), ((12, 18), .38), ((18, 24), .32))
        )
        hour = rng.randrange(*hour_range)
    if datetime(2027, 2, 8, tzinfo=UTC).date() <= current.date() <= datetime(2027, 3, 8, tzinfo=UTC).date():
        if channel in {"card", "cash_withdrawal"}:
            hour = rng.choice((hour, rng.randrange(18, 24), rng.randrange(0, 2)))
    return current.replace(hour=hour, minute=rng.randrange(60), second=rng.randrange(60),
                           microsecond=0)


def _customer_events(customer: Customer, seed: int) -> list[tuple[datetime, dict[str, Any]]]:
    # Per-account streams make generation independent of iteration/worker order.
    import hashlib

    account_seed = int.from_bytes(hashlib.sha256(f"{seed}:{customer.account_id}".encode()).digest()[:8], "big")
    rng = random.Random(account_seed)
    profile = PROFILES[customer.profile]
    rate = rng.gammavariate(4.0, profile["mean"] / 4.0) / DAYS
    size = _poisson(rng, rate * DAYS)
    events: list[tuple[datetime, dict[str, Any]]] = []
    for _ in range(size):
        channel = _weighted_choice(rng, profile["channels"].items())
        timestamp = _event_time(rng, customer.profile, channel)
        target = "ext-cash" if channel in {"cash_deposit", "cash_withdrawal"} else rng.choice(customer.counterparties)
        if channel == "card":
            target = rng.choice([account for account in customer.counterparties if account.startswith("ext-")])
        amount = round(rng.lognormvariate(math.log(profile["median"]), profile["sigma"]), 2)
        # Keep values finite and representable while preserving the long tail.
        amount = min(max(amount, .01), 10_000_000_000.00)
        city = customer.city if rng.random() < .9 else _weighted_choice(rng, [item for item in CITIES if item[0] != customer.city])
        event = {
            "tx_id": "", "timestamp": timestamp.isoformat(timespec="seconds").replace("+00:00", "Z"),
            "source_account_id": customer.account_id, "target_account_id": target,
            "amount": amount, "currency": "MAD", "channel": channel,
            "source_customer_type": customer.profile, "city": city,
        }
        events.append((timestamp, event))
    return sorted(events, key=lambda pair: (pair[0], customer.account_id))


def _customer_stream(customer: Customer, seed: int) -> Iterator[tuple[datetime, dict[str, Any]]]:
    yield from _customer_events(customer, seed)


def generate_transactions(*, profile: str = "light", seed: int = 42) -> Iterator[dict[str, Any]]:
    """Yield deterministic transactions, globally ordered by event time."""
    if profile not in {"light", "full"}:
        raise ValueError("profile must be 'light' or 'full'")
    customers = _population(5_000 if profile == "light" else 20_000, seed)
    # Heap merge the sorted per-customer streams while assigning globally stable IDs.
    streams = (_customer_stream(customer, seed) for customer in customers)
    merged = heapq.merge(*streams, key=lambda pair: (pair[0], pair[1]["source_account_id"]))
    for index, (_, event) in enumerate(merged, start=1):
        event["tx_id"] = f"tx-{index:08d}"
        validate_transaction(event)
        yield event


def write_csv(events: Iterable[dict[str, Any]], path: str | Path) -> int:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for event in events:
            writer.writerow(event)
            count += 1
    return count


def summarize_csv(path: str | Path) -> dict[str, Any]:
    profiles: Counter[str] = Counter()
    channels: Counter[str] = Counter()
    hours: Counter[int] = Counter()
    days: Counter[str] = Counter()
    count = 0
    with Path(path).open(encoding="utf-8", newline="") as handle:
        for event in csv.DictReader(handle):
            count += 1
            profiles[event["source_customer_type"]] += 1
            channels[event["channel"]] += 1
            timestamp = datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00"))
            hours[timestamp.hour] += 1
            days[timestamp.strftime("%A")] += 1
    return {"transactions": count, "by_profile": dict(sorted(profiles.items())),
            "by_channel": dict(sorted(channels.items())), "by_hour_utc": dict(sorted(hours.items())),
            "by_weekday": dict(sorted(days.items())), "scenario_counts": "non générés (tâche Mounir)",
            "labels": "aucun label dans le flux normal", "suspicious_rate": "non calculé avant intégration des scénarios"}


def read_csv(path: str | Path) -> Iterator[dict[str, Any]]:
    with Path(path).open(encoding="utf-8", newline="") as handle:
        for event in csv.DictReader(handle):
            event["amount"] = float(Decimal(event["amount"]))
            validate_transaction(event)
            yield event


def report_json(report: dict[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)


def publish_kafka(path: str | Path, *, rate: int, bootstrap_servers: str,
                  duration: float | None = None) -> int:
    """Replay a CSV into Kafka. Requires the optional ``streaming`` dependencies."""
    try:
        from confluent_kafka import Producer
    except ImportError as exc:
        raise RuntimeError("Installez les dépendances avec `pip install -e '.[streaming]'`.") from exc
    if not 1 <= rate <= 500:
        raise ValueError("rate must be between 1 and 500 events per second")
    if duration is not None and duration <= 0:
        raise ValueError("duration must be a positive number of seconds")
    producer = Producer({"bootstrap.servers": bootstrap_servers, "enable.idempotence": True,
                         "acks": "all", "client.id": "aml-normal-simulator"})
    sent = 0
    deadline = __import__("time").monotonic()
    started = __import__("time").monotonic()
    for event in read_csv(path):
        if duration is not None and __import__("time").monotonic() - started >= duration:
            break
        producer.produce("transactions", key=event["source_account_id"],
                         value=json.dumps(event, ensure_ascii=False, separators=(",", ":")))
        producer.poll(0)
        sent += 1
        deadline += 1 / rate
        delay = deadline - __import__("time").monotonic()
        if delay > 0:
            __import__("time").sleep(delay)
    remaining = producer.flush(60)
    if remaining:
        raise RuntimeError(f"{remaining} message(s) Kafka restent non livrés")
    return sent


def store_postgres(path: str | Path, *, dsn: str) -> int:
    """Idempotently persist raw transactions; requires the optional streaming extra."""
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("Installez les dépendances avec `pip install -e '.[streaming]'`.") from exc
    sql = """INSERT INTO raw_transactions
        (tx_id, event_ts, source_account_id, target_account_id, amount, currency, channel,
         source_customer_type, city, payload)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
        ON CONFLICT (tx_id) DO NOTHING"""
    count = 0
    with psycopg.connect(dsn) as connection, connection.cursor() as cursor:
        for event in read_csv(path):
            cursor.execute(sql, (event["tx_id"], event["timestamp"], event["source_account_id"],
                                 event["target_account_id"], event["amount"], event["currency"],
                                 event["channel"], event["source_customer_type"], event["city"],
                                 json.dumps(event, ensure_ascii=False)))
            count += cursor.rowcount
    return count
