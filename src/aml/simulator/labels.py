"""Labels de vérité terrain : schéma, validation, fichiers CSV et rapport de contrôle.

Les labels ne passent **jamais** par le topic Kafka ``transactions`` ni par le CSV de
transactions (le validateur ``validate_transaction`` rejette tout champ inconnu). Ils sont
écrits dans ``data/labels/`` ; le chargement dans la table PostgreSQL ``labels`` est une étape
d'intégration distincte (voir ``docs/journal.md``, Phase 3). Forme : ``docs/specification_
technique_aml.md`` section 8 (C-11).

Deux sortes de lignes, distinguées par ``tx_id`` :

* ligne **compte-rôle** (``tx_id`` vide) : un compte impliqué dans un cas, avec la période
  ``start_ts`` / ``end_ts`` de son activité de scénario ;
* ligne **transaction** (``tx_id`` renseigné) : une transaction « scénario », rattachée au
  compte du cas concerné (la source si c'est un compte du cas, sinon la cible).

Le camouflage (activité d'allure normale mêlée au cas) n'est pas étiqueté au niveau
transaction ; les comptes qui le produisent le sont au niveau compte.
"""

from __future__ import annotations

import csv
from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from aml.simulator.scenario_config import LEVELS, SCENARIOS

LABEL_FIELDS = (
    "account_id", "tx_id", "scenario", "role", "start_ts", "end_ts", "case_id", "sophistication",
)
ROLES = ("originator", "depositor", "intermediary", "mule", "beneficiary", "shell_company")


class LabelError(ValueError):
    """Ligne de label invalide."""


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)


def validate_label(row: Mapping[str, Any]) -> Mapping[str, Any]:
    """Valide une ligne de label (colonnes exactes, énumérations, période cohérente)."""
    if set(row) != set(LABEL_FIELDS):
        raise LabelError(f"colonnes attendues : {', '.join(LABEL_FIELDS)}")
    for name in ("account_id", "scenario", "role", "start_ts", "end_ts", "case_id"):
        if not isinstance(row[name], str) or not row[name]:
            raise LabelError(f"{name} doit être une chaîne non vide")
    if row["scenario"] not in SCENARIOS:
        raise LabelError(f"scenario inconnu : {row['scenario']!r}")
    if row["role"] not in ROLES:
        raise LabelError(f"role inconnu : {row['role']!r}")
    if row["sophistication"] not in LEVELS:
        raise LabelError(f"sophistication inconnue : {row['sophistication']!r}")
    if not isinstance(row["tx_id"], str):
        raise LabelError("tx_id doit être une chaîne (vide pour un label de compte)")
    if _parse(row["end_ts"]) < _parse(row["start_ts"]):
        raise LabelError("end_ts doit être postérieur ou égal à start_ts")
    return row


def write_labels(rows: Iterable[Mapping[str, Any]], path: str | Path) -> int:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=LABEL_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(validate_label(row))
            count += 1
    return count


def read_labels(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open(encoding="utf-8", newline="") as handle:
        return [dict(validate_label(row)) for row in csv.DictReader(handle)]


def scenario_report(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Champs du rapport ``simulate --report`` qui dépendent des scénarios et des labels."""
    cases: Counter[str] = Counter()
    for case in manifest["cases"]:
        cases[f"{case['scenario']}/{case['sophistication']}"] += 1
    rates = manifest["rates"]
    return {
        "scenario_counts": dict(sorted(cases.items())),
        "labels": {
            "labeled_accounts": rates["labeled_accounts"],
            "labeled_transactions": rates["labeled_transactions"],
            "camouflage_transactions": rates["camouflage_transactions"],
        },
        "suspicious_rate": {
            "accounts": rates["account_rate"],
            "transactions": rates["transaction_rate"],
            "accounts_below_limit": rates["account_rate"] < manifest["max_account_rate"],
        },
        "placement": manifest["placement_summary"],
    }
