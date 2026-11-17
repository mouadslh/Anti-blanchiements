"""Rules baseline: four simple, explainable rules driven by ``config/scoring.yaml``.

Each rule reads the backward-looking account features of the data contract (C-07) and, for two
rules, two optional *extension* features computed by ``aml.models.features`` (they are not in
contract v1, see ``docs/models_baseline.md``). A missing or null input never fires a rule.

Score convention (identical for every rule, so it is easy to explain):

* the rule does not fire -> score 0;
* the rule fires -> score 0.5 when its key quantity just reaches the configured threshold, rising
  linearly to 1.0 when it reaches ``saturation_multiple`` times that threshold.

The ``rules`` layer score is the maximum score of the fired rules, in [0, 1]. The output follows
the proposed scoring interface (``docs/specification_technique_aml.md``, C-08 and C-10): a
``rules`` entry for ``layer_scores``, a ``rules`` entry for ``model_versions``, and the
``fired_rules`` / ``typology_hint`` fields of ``explanation``.

No threshold is a legal obligation: every value comes from the configuration.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np

from aml.models.config import load_scoring_config

LAYER_NAME = "rules"
RULE_IDS = ("R-STRUCT-01", "R-RAPID-01", "R-DORM-01", "R-CHAN-01")

DESCRIPTIONS = {
    "R-STRUCT-01": (
        "Opérations en espèces répétées juste sous le seuil de référence configuré "
        "(fractionnement)"
    ),
    "R-RAPID-01": "Fonds reçus puis ressortis rapidement et presque en totalité",
    "R-DORM-01": "Compte peu actif pendant des semaines, puis brusquement très actif",
    "R-CHAN-01": "Volume élevé sur des canaux sensibles (espèces, virements internationaux)",
}
# The hint is only given when the rule is specific to one typology (never read from labels).
TYPOLOGY_HINTS: dict[str, str | None] = {
    "R-STRUCT-01": "structuring",
    "R-RAPID-01": None,
    "R-DORM-01": None,
    "R-CHAN-01": None,
}


@dataclass(frozen=True)
class RuleOutcome:
    rule_id: str
    description: str
    score: float


@dataclass(frozen=True)
class RuleResult:
    """Result of the rules layer for one (account, transaction)."""

    score: float
    fired_rules: tuple[RuleOutcome, ...]
    typology_hint: str | None

    def explanation_fields(self) -> dict[str, Any]:
        """The ``fired_rules`` and ``typology_hint`` keys of the alert ``explanation`` (C-10)."""
        return {
            "fired_rules": [
                {"rule_id": rule.rule_id, "description": rule.description}
                for rule in self.fired_rules
            ],
            "typology_hint": self.typology_hint,
        }


def _column(features: Mapping[str, Any], name: str) -> np.ndarray:
    """Return a float column; ``None`` and absent features become NaN (never fire a rule)."""
    value = features.get(name)
    if value is None:
        return np.full(1, np.nan)
    return np.asarray([value], dtype=float)


def _graded(value: np.ndarray, threshold: float, saturation: float) -> np.ndarray:
    """0.5 at the threshold, 1.0 at ``saturation`` x threshold (linear in between)."""
    ratio = np.divide(value, threshold, out=np.full_like(value, np.nan), where=threshold > 0)
    progress = np.clip((ratio - 1.0) / (saturation - 1.0), 0.0, 1.0)
    return 0.5 + 0.5 * progress


class RuleEngine:
    """Evaluate the four baseline rules on feature mappings or on column dictionaries."""

    def __init__(self, params: Mapping[str, Any]):
        self.params = dict(params)
        self.version = str(params["version"])
        self.saturation = float(params["saturation_multiple"])
        if self.saturation <= 1.0:
            raise ValueError("saturation_multiple must be greater than 1")
        self._rules: dict[str, Callable[[Mapping[str, np.ndarray]], np.ndarray]] = {}
        if params["structuring"]["enabled"]:
            self._rules["R-STRUCT-01"] = self._structuring
        if params["rapid_in_out"]["enabled"]:
            self._rules["R-RAPID-01"] = self._rapid_in_out
        if params["dormant_then_active"]["enabled"]:
            self._rules["R-DORM-01"] = self._dormant_then_active
        if params["risky_channel"]["enabled"]:
            self._rules["R-CHAN-01"] = self._risky_channel

    @classmethod
    def from_config(cls, config: Mapping[str, Any] | None = None) -> RuleEngine:
        return cls((config or load_scoring_config())["rules"])

    @property
    def rule_ids(self) -> tuple[str, ...]:
        return tuple(self._rules)

    # -- the four rules: each returns an array of scores in {0} U [0.5, 1] ----------------------

    def _structuring(self, col: Mapping[str, np.ndarray]) -> np.ndarray:
        p = self.params["structuring"]
        near_count = np.rint(col["near_threshold_share_7d"] * col["tx_count_7d"])
        fired = (near_count >= p["min_near_threshold_count_7d"]) & (
            col["cash_share_7d"] >= p["min_cash_share_7d"]
        )
        graded = _graded(near_count, p["min_near_threshold_count_7d"], self.saturation)
        return np.where(fired, graded, 0.0)

    def _rapid_in_out(self, col: Mapping[str, np.ndarray]) -> np.ndarray:
        p = self.params["rapid_in_out"]
        delay = col["avg_in_to_out_delay_s_24h"]
        ratio = col["inflow_outflow_ratio_24h"]
        fired = (
            (delay <= p["max_avg_delay_s_24h"])
            & (col["total_amount_24h_mad"] >= p["min_total_amount_24h_mad"])
            & (ratio >= p["min_inflow_outflow_ratio_24h"])
            & (ratio <= p["max_inflow_outflow_ratio_24h"])
        )
        speed = np.divide(p["max_avg_delay_s_24h"], np.maximum(delay, 1.0))
        graded = _graded(speed, 1.0, self.saturation)
        return np.where(fired, graded, 0.0)

    def _dormant_then_active(self, col: Mapping[str, np.ndarray]) -> np.ndarray:
        p = self.params["dormant_then_active"]
        count = col["tx_count_7d"]
        fired = (
            (col["tx_count_7d_to_30d"] <= p["max_baseline_tx_count"])
            & (count >= p["min_tx_count_7d"])
            & (col["total_amount_7d_mad"] >= p["min_total_amount_7d_mad"])
        )
        return np.where(fired, _graded(count, p["min_tx_count_7d"], self.saturation), 0.0)

    def _risky_channel(self, col: Mapping[str, np.ndarray]) -> np.ndarray:
        p = self.params["risky_channel"]
        international = np.nan_to_num(col["international_share_24h"], nan=0.0)
        risky_share = col["cash_share_24h"] + international
        amount = col["total_amount_24h_mad"]
        fired = (
            (risky_share >= p["min_risky_share_24h"])
            & (col["tx_count_24h"] >= p["min_tx_count_24h"])
            & (amount >= p["min_total_amount_24h_mad"])
        )
        return np.where(fired, _graded(amount, p["min_total_amount_24h_mad"], self.saturation), 0.0)

    # -- public API --------------------------------------------------------------------------

    _INPUTS = (
        "tx_count_24h", "tx_count_7d", "total_amount_24h_mad", "total_amount_7d_mad",
        "near_threshold_share_7d", "cash_share_24h", "cash_share_7d",
        "inflow_outflow_ratio_24h", "avg_in_to_out_delay_s_24h",
        "tx_count_7d_to_30d", "international_share_24h",
    )

    def score_columns(self, columns: Mapping[str, np.ndarray]) -> dict[str, np.ndarray]:
        """Per-rule score arrays from column arrays (NaN = missing). Used for batch evaluation."""
        filled = {
            name: np.asarray(columns[name], dtype=float)
            if name in columns
            else np.full(_length(columns), np.nan)
            for name in self._INPUTS
        }
        return {rule_id: rule(filled) for rule_id, rule in self._rules.items()}

    def layer_score_columns(self, columns: Mapping[str, np.ndarray]) -> np.ndarray:
        """The ``rules`` layer score for each row: maximum over the fired rules."""
        scores = self.score_columns(columns)
        if not scores:
            return np.zeros(_length(columns))
        return np.max(np.vstack(list(scores.values())), axis=0)

    def evaluate(self, features: Mapping[str, Any]) -> RuleResult:
        """Evaluate one feature message (``features`` object of a C-06 message)."""
        scores = self.score_columns({name: _column(features, name) for name in self._INPUTS})
        fired = tuple(
            RuleOutcome(rule_id, DESCRIPTIONS[rule_id], round(float(values[0]), 6))
            for rule_id, values in scores.items()
            if values[0] > 0
        )
        fired = tuple(sorted(fired, key=lambda rule: (-rule.score, rule.rule_id)))
        score = max((rule.score for rule in fired), default=0.0)
        hint = TYPOLOGY_HINTS[fired[0].rule_id] if fired else None
        return RuleResult(score=score, fired_rules=fired, typology_hint=hint)


def _length(columns: Mapping[str, Any]) -> int:
    for value in columns.values():
        return len(value)
    return 0
