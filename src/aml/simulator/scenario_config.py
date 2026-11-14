"""Configuration des scénarios AML : paramètres, niveaux de sophistication, placement.

Toutes les valeurs par défaut sont des hypothèses de simulation **[H]** tirées de
``docs/typologies.md`` (sections 4 et 5). Les paramètres qui n'y figurent pas et que le
simulateur a dû ajouter sont signalés « [H] nouveau » ; ils sont listés dans
``docs/journal.md`` (Phase 3). Le fichier ``config/simulator.yaml`` reprend ces défauts
et sert de point de départ aux surcharges (test ``test_default_yaml_matches_code``).
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from aml.simulator.normal import DAYS

SCENARIOS = ("structuring", "layering", "mule", "round_tripping", "shell_company")
LEVELS = ("low", "medium", "high")
BLOCK_NAMES = ("train", "validation", "test")
BLOCK_ASSIGNMENTS = ("any", "per_block")
# Les valeurs de ces clés remplacent la valeur par défaut au lieu d'être fusionnées.
REPLACE_KEYS = frozenset({"cases"})


class ScenarioConfigError(ValueError):
    """Configuration de scénario invalide ou impossible à placer."""


DEFAULT_CONFIG: dict[str, Any] = {
    # H-01 : hypothèse de simulation, jamais une obligation légale marocaine.
    "reporting_threshold": 100_000,
    # Contrainte de la question centrale (D-2) : taux de comptes étiquetés < 1 %.
    "max_account_rate": 0.01,
    "placement": {
        # Jours 1 à 7 : échauffement, aucun cas (docs/evaluation_plan.md, 2.2).
        "first_case_day": 8,
        "blocks": {"train": [8, 56], "validation": [57, 72], "test": [73, 90]},
    },
    "profiles": {
        # D-3 : 1 cas par scénario (niveau medium, [H]) ; usage fonctionnel seulement.
        "light": {
            "block_assignment": "any",
            "cases": {name: {"medium": 1} for name in SCENARIOS},
        },
        # D-4 : 1 cas par couple scénario x niveau ; chaque scénario place un cas par
        # bloc avec une permutation des niveaux tirée de la graine (evaluation_plan 2.5).
        "full": {
            "block_assignment": "per_block",
            "cases": {name: {"low": 1, "medium": 1, "high": 1} for name in SCENARIOS},
        },
    },
    "scenarios": {
        "structuring": {
            "base": {
                "n_accounts_in_group": 2,
                "deposits_per_account": 10,
                "amount_fraction_range": [0.75, 0.99],
                "window_days": 14,
                "n_cities": 2,
                "consolidation_delay_days": 3,
                "normal_mix_ratio": 0.3,
            },
            "levels": {
                "low": {"n_accounts_in_group": 1, "amount_fraction_range": [0.90, 0.99],
                        "n_cities": 1, "normal_mix_ratio": 0.0},
                "medium": {"n_accounts_in_group": [2, 3], "amount_fraction_range": [0.75, 0.99],
                           "n_cities": 2, "normal_mix_ratio": 0.3},
                "high": {"n_accounts_in_group": [3, 5], "amount_fraction_range": [0.50, 0.99],
                         "n_cities": [2, 4], "normal_mix_ratio": 0.6},
            },
        },
        "layering": {
            "base": {
                "chain_length": 5,
                "hop_delay_minutes_range": [30, 360],
                "fee_rate_per_hop": 0.01,
                "initial_amount_multiple": 3,
                "n_parallel_branches": 2,
                "international_exit_prob": 0.2,
            },
            "levels": {
                "low": {"hop_delay_minutes_range": [5, 60], "n_parallel_branches": 1},
                "medium": {"hop_delay_minutes_range": [30, 360], "n_parallel_branches": 2},
                "high": {"hop_delay_minutes_range": [60, 2880], "n_parallel_branches": 3},
            },
        },
        "mule": {
            "base": {
                "n_mules": 8,
                "n_inbound_sources": 12,
                "forward_ratio": 0.90,
                "forward_delay_hours_range": [2, 24],
                "n_destinations": 2,
                "cash_out_share": 0.3,
                "account_age_days": 60,
                "normal_mix_ratio": 0.4,
                # [H] nouveau : fenêtre de réception des virements et montant médian.
                "inbound_window_days": 3,
                "inbound_amount_median": 5000,
            },
            "levels": {
                "low": {"forward_delay_hours_range": [0.5, 6], "normal_mix_ratio": 0.0},
                "medium": {"forward_delay_hours_range": [2, 24], "normal_mix_ratio": 0.4},
                "high": {"forward_delay_hours_range": [6, 72], "normal_mix_ratio": 0.7},
            },
        },
        "round_tripping": {
            "base": {
                "cycle_length": 4,
                "n_companies_in_loop": 3,
                "loss_per_loop": 0.02,
                "n_repeats": 2,
                # Durée maximale : les délais sont réduits si le cycle dépasse cette durée.
                "period_days": 30,
                "round_amount_share": 0.4,
                "loop_delay_days": 2,
                # [H] nouveau : montant initial (multiple de T) et mélange de contreparties.
                "initial_amount_multiple": 0.5,
                "normal_mix_ratio": 0.1,
            },
            "levels": {
                "low": {"cycle_length": 3, "round_amount_share": 0.8, "loop_delay_days": 1,
                        "normal_mix_ratio": 0.0},
                "medium": {"cycle_length": [4, 5], "round_amount_share": 0.4,
                           "loop_delay_days": 2, "normal_mix_ratio": 0.1},
                "high": {"cycle_length": [5, 6], "round_amount_share": 0.1,
                         "loop_delay_days": 3, "normal_mix_ratio": 0.3},
            },
        },
        "shell_company": {
            "base": {
                "n_shells": 4,
                "inflow_multiple": 10,
                "n_distinct_counterparties": 4,
                "payroll_like_outflow_share": 0.05,
                "international_share": 0.3,
                "dormancy_days": 30,
                "facade_activity_ratio": 0.1,
                # [H] nouveau : durée du pic d'activité et montant médian des dépenses de façade.
                "active_days": 10,
                "facade_amount_median": 1200,
            },
            "levels": {
                "low": {"n_distinct_counterparties": [2, 3], "payroll_like_outflow_share": 0.0,
                        "facade_activity_ratio": 0.0},
                "medium": {"n_distinct_counterparties": [4, 6],
                           "payroll_like_outflow_share": 0.05, "facade_activity_ratio": 0.1},
                "high": {"n_distinct_counterparties": [6, 10],
                         "payroll_like_outflow_share": 0.15, "facade_activity_ratio": 0.3},
            },
        },
    },
}

# (minimum, maximum, entier ?) : plages du catalogue (docs/typologies.md, section 4).
PARAM_BOUNDS: dict[str, dict[str, tuple[float, float, bool]]] = {
    "structuring": {
        "n_accounts_in_group": (1, 5, True),
        "deposits_per_account": (4, 30, True),
        "amount_fraction_range": (0.05, 0.999, False),
        "window_days": (3, 30, True),
        "n_cities": (1, 4, True),
        "consolidation_delay_days": (0, 10, True),
        "normal_mix_ratio": (0, 0.7, False),
    },
    "layering": {
        "chain_length": (3, 8, True),
        "hop_delay_minutes_range": (1, 2880, False),
        "fee_rate_per_hop": (0.005, 0.03, False),
        "initial_amount_multiple": (0.5, 10, False),
        "n_parallel_branches": (1, 3, True),
        "international_exit_prob": (0, 0.6, False),
    },
    "mule": {
        "n_mules": (3, 20, True),
        "n_inbound_sources": (5, 30, True),
        "forward_ratio": (0.80, 0.98, False),
        "forward_delay_hours_range": (0.1, 72, False),
        "n_destinations": (1, 3, True),
        "cash_out_share": (0, 0.6, False),
        "account_age_days": (10, 365, True),
        "normal_mix_ratio": (0, 0.8, False),
        "inbound_window_days": (1, 14, True),
        "inbound_amount_median": (500, 50_000, False),
    },
    "round_tripping": {
        "cycle_length": (3, 6, True),
        "n_companies_in_loop": (2, 5, True),
        "loss_per_loop": (0, 0.05, False),
        "n_repeats": (1, 5, True),
        "period_days": (7, 60, True),
        "round_amount_share": (0, 1, False),
        "loop_delay_days": (0, 10, False),
        "initial_amount_multiple": (0.2, 10, False),
        "normal_mix_ratio": (0, 0.7, False),
    },
    "shell_company": {
        "n_shells": (2, 10, True),
        "inflow_multiple": (3, 50, False),
        "n_distinct_counterparties": (2, 10, True),
        "payroll_like_outflow_share": (0, 0.2, False),
        "international_share": (0, 0.7, False),
        "dormancy_days": (0, 90, True),
        "facade_activity_ratio": (0, 0.5, False),
        "active_days": (3, 30, True),
        "facade_amount_median": (50, 20_000, False),
    },
}


def deep_merge(base: Mapping[str, Any], overrides: Mapping[str, Any]) -> dict[str, Any]:
    """Fusionne récursivement ``overrides`` dans une copie de ``base``."""
    merged = copy.deepcopy(dict(base))
    for key, value in overrides.items():
        if key in REPLACE_KEYS or not isinstance(value, Mapping):
            merged[key] = copy.deepcopy(value)
        elif isinstance(merged.get(key), Mapping):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(dict(value))
    return merged


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _check_scalar(where: str, value: Any, lo: float, hi: float, integer: bool) -> None:
    if not _is_number(value):
        raise ScenarioConfigError(f"{where}: nombre attendu, reçu {value!r}")
    if integer and not isinstance(value, int):
        raise ScenarioConfigError(f"{where}: entier attendu, reçu {value!r}")
    if not lo <= value <= hi:
        raise ScenarioConfigError(f"{where}: {value} hors de la plage [{lo}, {hi}]")


def _check_pair(where: str, value: Any, lo: float, hi: float, integer: bool) -> None:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ScenarioConfigError(f"{where}: paire [min, max] attendue, reçu {value!r}")
    for item in value:
        _check_scalar(where, item, lo, hi, integer)
    if value[0] > value[1]:
        raise ScenarioConfigError(f"{where}: min {value[0]} supérieur à max {value[1]}")


def _check_param(where: str, name: str, value: Any, bounds: tuple[float, float, bool]) -> None:
    lo, hi, integer = bounds
    if name.endswith("_range"):
        _check_pair(where, value, lo, hi, False)
    elif isinstance(value, (list, tuple)):
        _check_pair(where, value, lo, hi, integer)
    else:
        _check_scalar(where, value, lo, hi, integer)


def _validate_scenarios(config: Mapping[str, Any]) -> None:
    scenarios = config.get("scenarios")
    if not isinstance(scenarios, Mapping):
        raise ScenarioConfigError("scenarios: section manquante")
    unknown = set(scenarios) - set(SCENARIOS)
    if unknown:
        raise ScenarioConfigError(f"scénario inconnu : {', '.join(sorted(unknown))}")
    for scenario in SCENARIOS:
        spec = scenarios.get(scenario)
        if not isinstance(spec, Mapping) or "base" not in spec or "levels" not in spec:
            raise ScenarioConfigError(f"{scenario}: sections 'base' et 'levels' requises")
        bounds = PARAM_BOUNDS[scenario]
        for level in spec["levels"]:
            if level not in LEVELS:
                raise ScenarioConfigError(f"{scenario}: niveau inconnu {level!r}")
        for level in LEVELS:
            merged = {**spec["base"], **spec["levels"].get(level, {})}
            where_prefix = f"{scenario}.{level}"
            if set(merged) - set(bounds):
                extra = ", ".join(sorted(set(merged) - set(bounds)))
                raise ScenarioConfigError(f"{where_prefix}: paramètre inconnu : {extra}")
            if set(bounds) - set(merged):
                missing = ", ".join(sorted(set(bounds) - set(merged)))
                raise ScenarioConfigError(f"{where_prefix}: paramètre manquant : {missing}")
            for name, value in merged.items():
                _check_param(f"{where_prefix}.{name}", name, value, bounds[name])


def _validate_profiles(config: Mapping[str, Any]) -> None:
    profiles = config.get("profiles")
    if not isinstance(profiles, Mapping):
        raise ScenarioConfigError("profiles: section manquante")
    for name in ("light", "full"):
        profile = profiles.get(name)
        if not isinstance(profile, Mapping):
            raise ScenarioConfigError(f"profiles.{name}: section manquante")
        if profile.get("block_assignment") not in BLOCK_ASSIGNMENTS:
            raise ScenarioConfigError(
                f"profiles.{name}.block_assignment doit valoir {' ou '.join(BLOCK_ASSIGNMENTS)}"
            )
        cases = profile.get("cases")
        if not isinstance(cases, Mapping):
            raise ScenarioConfigError(f"profiles.{name}.cases: table scénario -> niveau -> nombre")
        for scenario, levels in cases.items():
            if scenario not in SCENARIOS or not isinstance(levels, Mapping):
                raise ScenarioConfigError(f"profiles.{name}.cases: scénario invalide {scenario!r}")
            for level, count in levels.items():
                if level not in LEVELS:
                    raise ScenarioConfigError(f"profiles.{name}.cases.{scenario}: niveau {level!r}")
                if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                    raise ScenarioConfigError(
                        f"profiles.{name}.cases.{scenario}.{level}: entier >= 0 attendu"
                    )


def _validate_global(config: Mapping[str, Any]) -> None:
    threshold = config.get("reporting_threshold")
    if not _is_number(threshold) or threshold <= 0:
        raise ScenarioConfigError("reporting_threshold doit être un nombre strictement positif")
    rate = config.get("max_account_rate")
    if not _is_number(rate) or not 0 < rate <= 1:
        raise ScenarioConfigError("max_account_rate doit être dans l'intervalle ]0, 1]")
    placement = config.get("placement")
    if not isinstance(placement, Mapping):
        raise ScenarioConfigError("placement: section manquante")
    first = placement.get("first_case_day")
    if not isinstance(first, int) or not 1 <= first <= DAYS:
        raise ScenarioConfigError(f"placement.first_case_day doit être un jour entre 1 et {DAYS}")
    blocks = placement.get("blocks")
    if not isinstance(blocks, Mapping) or set(blocks) != set(BLOCK_NAMES):
        raise ScenarioConfigError(f"placement.blocks doit définir {', '.join(BLOCK_NAMES)}")
    for name, bounds in blocks.items():
        if (
            not isinstance(bounds, (list, tuple))
            or len(bounds) != 2
            or not all(isinstance(day, int) for day in bounds)
            or not 1 <= bounds[0] <= bounds[1] <= DAYS
        ):
            raise ScenarioConfigError(f"placement.blocks.{name}: [jour_debut, jour_fin] dans 1..{DAYS}")


def load_config(overrides: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Retourne la configuration par défaut fusionnée avec ``overrides`` et validée."""
    config = deep_merge(DEFAULT_CONFIG, overrides or {})
    _validate_global(config)
    _validate_scenarios(config)
    _validate_profiles(config)
    return config


def load_config_file(path: str | Path) -> dict[str, Any]:
    """Charge un fichier YAML de surcharges (PyYAML requis) puis valide le résultat."""
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("Installez PyYAML avec `pip install -e '.[dev]'` ou `pip install pyyaml`.") from exc
    with Path(path).open(encoding="utf-8") as handle:
        overrides = yaml.safe_load(handle) or {}
    if not isinstance(overrides, Mapping):
        raise ScenarioConfigError(f"{path}: le fichier doit contenir une table YAML")
    return load_config(overrides)


def resolve_params(rng: Any, config: Mapping[str, Any], scenario: str, level: str) -> dict[str, Any]:
    """Tire les paramètres d'un cas : base + niveau, les paires [min, max] sont échantillonnées.

    Les clés ``*_range`` restent des intervalles (utilisés événement par événement).
    """
    spec = config["scenarios"][scenario]
    merged = {**spec["base"], **spec["levels"].get(level, {})}
    resolved: dict[str, Any] = {}
    for name, value in merged.items():
        if name.endswith("_range"):
            resolved[name] = (float(value[0]), float(value[1]))
        elif isinstance(value, (list, tuple)):
            low, high = value
            if isinstance(low, int) and isinstance(high, int):
                resolved[name] = rng.randint(low, high)
            else:
                resolved[name] = round(rng.uniform(low, high), 4)
        else:
            resolved[name] = value
    return resolved
