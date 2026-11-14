"""Jeu de données complet : flux normal + scénarios AML injectés + labels séparés.

Le flux d'événements produit ici respecte exactement le contrat ``transactions`` v1 : les
événements de scénario sont indiscernables des événements normaux par leur forme. Les
labels, les rôles et les paramètres réalisés sont retournés à part (``Dataset.labels()`` et
``Dataset.manifest()``) et écrits dans ``data/labels/`` par ``write_dataset``.

Sans cas configuré, le flux est identique à celui de ``normal.generate_transactions``.
"""

from __future__ import annotations

import hashlib
import heapq
import json
import random
from collections import Counter
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from aml.common.schemas import validate_transaction
from aml.simulator.labels import LABEL_FIELDS, write_labels
from aml.simulator.normal import (
    DAYS,
    START,
    Customer,
    _customer_stream,
    _population,
    write_csv,
)
from aml.simulator.scenario_config import (
    BLOCK_NAMES,
    LEVELS,
    SCENARIOS,
    ScenarioConfigError,
    load_config,
    resolve_params,
)
from aml.simulator.scenarios import BUILDERS, AccountPool, Context, Draft, external_count

END = START + timedelta(days=DAYS)
POPULATION = {"light": 5_000, "full": 20_000}


def _derive(*parts: object) -> int:
    digest = hashlib.sha256(":".join(map(str, parts)).encode()).digest()
    return int.from_bytes(digest[:8], "big")


def _snap_business(moment: datetime, seq: int) -> datetime:
    """Ramène un instant au prochain créneau ouvré (lun-ven, 9 h - 17 h), ordre conservé."""
    shifted = False
    while True:
        if moment.weekday() >= 5 or moment.hour >= 17:
            moment = (moment + timedelta(days=1)).replace(hour=9, minute=0, second=0)
        elif moment.hour < 9:
            moment = moment.replace(hour=9, minute=0, second=0)
        else:
            break
        shifted = True
    return moment + timedelta(seconds=seq) if shifted else moment


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _iso(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class _Meta:
    uid: tuple[int, int]  # (index du cas, numéro d'événement dans le cas)
    labeled: bool


@dataclass
class PlannedCase:
    index: int
    draft: Draft
    assigned_block: str | None
    block: str  # bloc effectif, ou « cross » si le cas chevauche plusieurs blocs
    start_day: int
    start: datetime
    fits_single_block: bool
    events: list[tuple[datetime, Any, int]]  # (instant, événement relatif, numéro)

    @property
    def case_id(self) -> str:
        return f"case-{self.index:03d}"


def _place(rng: random.Random, span: timedelta, config: Mapping[str, Any],
           assigned: str | None) -> tuple[int, str, bool]:
    """Choisit le jour de début d'un cas : dans un seul bloc d'évaluation si possible (L-6)."""
    first = config["placement"]["first_case_day"]
    length = int(span.total_seconds() // 86400)
    windows: dict[str, tuple[int, int]] = {}
    for name in BLOCK_NAMES:
        low, high = config["placement"]["blocks"][name]
        low, high = max(low, first), high - length
        if high >= low:
            windows[name] = (low, high)
    if assigned in windows:
        return rng.randint(*windows[assigned]), assigned, True
    if windows:
        names = sorted(windows)
        widths = [windows[item][1] - windows[item][0] + 1 for item in names]
        if assigned is None:
            name = rng.choices(names, weights=widths)[0]  # tirage proportionnel à la durée
        else:
            # Le bloc prévu ne peut pas accueillir le cas : on prend le bloc le plus large.
            name = names[widths.index(max(widths))]
        return rng.randint(*windows[name]), name, True
    high = DAYS - length
    if high < first:
        raise ScenarioConfigError(
            f"un cas de {span.total_seconds() / 86400:.1f} jours ne tient pas dans la période "
            f"de {DAYS} jours : raccourcir ses durées (question ouverte 3)"
        )
    return rng.randint(first, high), "cross", False


class Dataset:
    """Plan déterministe des cas puis génération du flux fusionné et des labels."""

    def __init__(self, profile: str = "light", seed: int = 42,
                 config: Mapping[str, Any] | None = None, *,
                 population_size: int | None = None) -> None:
        if profile not in POPULATION:
            raise ValueError("profile must be 'light' or 'full'")
        self.profile = profile
        self.seed = seed
        self.config = load_config(config)
        self.population_size = population_size or POPULATION[profile]
        self.customers: list[Customer] = _population(self.population_size, seed)
        self.cases: list[PlannedCase] = []
        self._quiet: dict[str, list[tuple[datetime | None, datetime]]] = {}
        self._scenario_events: list[tuple[datetime, str, dict[str, Any], _Meta]] = []
        self._tx_ids: dict[tuple[int, int], str] = {}
        self._total = 0
        self._suppressed = 0
        self._started = False
        self._consumed = False
        self._plan()

    # ------------------------------------------------------------------ planification

    def _specs(self) -> list[tuple[str, str, str | None]]:
        profile = self.config["profiles"][self.profile]
        per_block = profile["block_assignment"] == "per_block"
        specs: list[tuple[str, str, str | None]] = []
        for scenario in SCENARIOS:
            counts = profile["cases"].get(scenario, {})
            levels = [level for level in LEVELS for _ in range(counts.get(level, 0))]
            if per_block:
                # Un cas par bloc, permutation des niveaux tirée de la graine (plan 2.5).
                random.Random(_derive(self.seed, "levels", scenario)).shuffle(levels)
            for number, level in enumerate(levels):
                block = BLOCK_NAMES[number % len(BLOCK_NAMES)] if per_block else None
                specs.append((scenario, level, block))
        return specs

    def _plan(self) -> None:
        config = self.config
        context = Context(AccountPool(self.customers), float(config["reporting_threshold"]),
                          external_count(self.population_size))
        for index, (scenario, level, assigned) in enumerate(self._specs(), start=1):
            rng = random.Random(_derive(self.seed, "case", index, scenario, level))
            params = resolve_params(rng, config, scenario, level)
            draft = BUILDERS[scenario](rng, context, level, params)
            place_rng = random.Random(_derive(self.seed, "placement", index))
            day, block, fits = _place(place_rng, draft.span(), config, assigned)
            self.cases.append(self._materialize(index, draft, assigned, block, day, fits))
        accounts = {account for case in self.cases for account in case.draft.roles}
        rate = len(accounts) / self.population_size
        if rate >= config["max_account_rate"]:
            raise ScenarioConfigError(
                f"taux de comptes étiquetés {rate:.2%} >= limite {config['max_account_rate']:.2%} "
                f"({len(accounts)} comptes sur {self.population_size}) : réduire les cas ou "
                "augmenter la population (décision D-2)"
            )
        self._scenario_events.sort(key=lambda item: (item[0], item[1], item[3].uid))

    def _materialize(self, index: int, draft: Draft, assigned: str | None, block: str,
                     day: int, fits: bool) -> PlannedCase:
        start = START + timedelta(days=day - 1)
        timed: list[tuple[datetime, Any, int]] = []
        for seq, event in enumerate(draft.events):
            moment = start + event.offset
            if event.business:
                moment = _snap_business(moment, seq)
            moment = moment.replace(microsecond=0)
            if moment >= END:
                raise ScenarioConfigError(f"case-{index:03d}: événement après la fin de période")
            if event.source.account_id == event.target:
                raise ScenarioConfigError(f"case-{index:03d}: source et cible identiques")
            payload = {
                "tx_id": "", "timestamp": _iso(moment),
                "source_account_id": event.source.account_id, "target_account_id": event.target,
                "amount": event.amount, "currency": "MAD", "channel": event.channel,
                "source_customer_type": event.source.profile, "city": event.city,
            }
            meta = _Meta((index, seq), event.labeled)
            self._scenario_events.append((moment, event.source.account_id, payload, meta))
            timed.append((moment, event, seq))
        for quiet in draft.quiet:
            window = (None if quiet.start is None else start + quiet.start, start + quiet.end)
            self._quiet.setdefault(quiet.account_id, []).append(window)
        return PlannedCase(index, draft, assigned, block, day, start, fits, timed)

    # ----------------------------------------------------------------------- flux

    def _normal_stream(self, customer: Customer) -> Iterator[tuple[datetime, str, Any, None]]:
        windows = self._quiet.get(customer.account_id)
        for moment, event in _customer_stream(customer, self.seed):
            if windows and any((low is None or moment >= low) and moment < high
                               for low, high in windows):
                self._suppressed += 1
                continue
            yield moment, event["source_account_id"], event, None

    def events(self) -> Iterator[dict[str, Any]]:
        """Flux global ordonné par temps événementiel, sans aucun champ de label."""
        if self._started:
            raise RuntimeError("Dataset.events() ne peut être consommé qu'une fois")
        self._started = True
        streams = [self._normal_stream(customer) for customer in self.customers]
        merged = heapq.merge(*streams, iter(self._scenario_events),
                             key=lambda item: (item[0], item[1]))
        for index, (_, _, event, meta) in enumerate(merged, start=1):
            event["tx_id"] = f"tx-{index:08d}"
            validate_transaction(event)
            if meta is not None and meta.labeled:
                self._tx_ids[meta.uid] = event["tx_id"]
            self._total = index
            yield event
        self._consumed = True

    # ---------------------------------------------------------------------- labels

    def _require_consumed(self) -> None:
        if not self._consumed:
            raise RuntimeError("consommer entièrement Dataset.events() avant les labels")

    def _case_rows(self, case: PlannedCase) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
        roles = case.draft.roles
        activity: dict[str, list[datetime]] = {}
        transactions: list[dict[str, str]] = []
        common = {"scenario": case.draft.scenario, "case_id": case.case_id,
                  "sophistication": case.draft.level}
        for moment, event, seq in case.events:
            if not event.labeled:
                continue
            for account in (event.source.account_id, event.target):
                if account in roles:
                    activity.setdefault(account, []).append(moment)
            owner = event.source.account_id if event.source.account_id in roles else event.target
            transactions.append({
                "account_id": owner, "tx_id": self._tx_ids[(case.index, seq)],
                "role": roles[owner], "start_ts": _iso(moment), "end_ts": _iso(moment), **common,
            })
        accounts = []
        for account, role in sorted(roles.items()):
            if account not in activity:
                raise ScenarioConfigError(f"{case.case_id}: compte {account} sans activité")
            accounts.append({
                "account_id": account, "tx_id": "", "role": role,
                "start_ts": _iso(min(activity[account])), "end_ts": _iso(max(activity[account])),
                **common,
            })
        return accounts, sorted(transactions, key=lambda row: row["tx_id"])

    def labels(self) -> list[dict[str, str]]:
        """Lignes de labels : d'abord les comptes de chaque cas, puis ses transactions."""
        self._require_consumed()
        rows: list[dict[str, str]] = []
        for case in self.cases:
            accounts, transactions = self._case_rows(case)
            rows.extend(accounts)
            rows.extend(transactions)
        return [{name: row[name] for name in LABEL_FIELDS} for row in rows]

    def manifest(self) -> dict[str, Any]:
        """Paramètres réalisés, placement et taux mesurés (sorties de contrôle D-1, D-2)."""
        self._require_consumed()
        cases = []
        labeled_accounts: set[str] = set()
        labeled_total = camouflage_total = 0
        placement: Counter[str] = Counter()
        for case in self.cases:
            labeled = [moment for moment, event, _ in case.events if event.labeled]
            camouflage = len(case.events) - len(labeled)
            labeled_accounts.update(case.draft.roles)
            labeled_total += len(labeled)
            camouflage_total += camouflage
            placement[case.block] += 1
            cases.append({
                "case_id": case.case_id, "scenario": case.draft.scenario,
                "sophistication": case.draft.level, "assigned_block": case.assigned_block,
                "block": case.block, "fits_single_block": case.fits_single_block,
                "start_day": case.start_day, "start_ts": _iso(min(labeled)),
                "end_ts": _iso(max(labeled)), "accounts": len(case.draft.roles),
                "labeled_transactions": len(labeled), "camouflage_transactions": camouflage,
                "params": _jsonable(case.draft.params),
            })
        return {
            "profile": self.profile, "seed": self.seed, "population_size": self.population_size,
            "period": {"start": _iso(START), "days": DAYS},
            "reporting_threshold": self.config["reporting_threshold"],
            "max_account_rate": self.config["max_account_rate"],
            "block_assignment": self.config["profiles"][self.profile]["block_assignment"],
            "cases": cases,
            "rates": {
                "labeled_accounts": len(labeled_accounts), "labeled_transactions": labeled_total,
                "camouflage_transactions": camouflage_total, "total_transactions": self._total,
                "suppressed_normal_events": self._suppressed,
                "account_rate": round(len(labeled_accounts) / self.population_size, 6),
                "transaction_rate": round(labeled_total / self._total, 6) if self._total else 0.0,
            },
            "placement_summary": {
                "by_block": dict(sorted(placement.items())),
                "cases_outside_assigned_block": sum(
                    1 for case in self.cases
                    if case.assigned_block is not None and case.block != case.assigned_block),
                "cases_not_in_single_block": sum(
                    1 for case in self.cases if not case.fits_single_block),
            },
            "config": _jsonable(self.config),
        }


def build_dataset(profile: str = "light", seed: int = 42, config: Mapping[str, Any] | None = None,
                  *, population_size: int | None = None) -> Dataset:
    return Dataset(profile, seed, config, population_size=population_size)


def generate_dataset(profile: str = "light", seed: int = 42,
                     config: Mapping[str, Any] | None = None, *,
                     population_size: int | None = None
                     ) -> tuple[list[dict[str, Any]], list[dict[str, str]], dict[str, Any]]:
    """Version en mémoire : (transactions, labels, manifeste). Pour les tests et petits jeux."""
    dataset = build_dataset(profile, seed, config, population_size=population_size)
    events = list(dataset.events())
    return events, dataset.labels(), dataset.manifest()


def write_dataset(dataset: Dataset, transactions_path: str | Path, labels_path: str | Path,
                  manifest_path: str | Path | None = None) -> dict[str, Any]:
    """Écrit le CSV de transactions, le CSV de labels (séparé) et le manifeste JSON."""
    write_csv(dataset.events(), transactions_path)
    write_labels(dataset.labels(), labels_path)
    manifest = dataset.manifest()
    if manifest_path is not None:
        output = Path(manifest_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
                          encoding="utf-8")
    return manifest

