import copy
import json
import re
from pathlib import Path

import numpy as np
import pytest

from aml.common.schemas import validate_alert, validate_score
from aml.models.config import ROOT, load_scoring_config
from aml.models.rules import DESCRIPTIONS, RULE_IDS, RuleEngine

CONFIG = load_scoring_config()
PARAMS = CONFIG["rules"]
SATURATION = PARAMS["saturation_multiple"]


def benign() -> dict:
    """A feature message that fires no rule."""
    return {
        "tx_count_24h": 1, "tx_count_7d": 2, "total_amount_24h_mad": 100.0,
        "total_amount_7d_mad": 200.0, "near_threshold_share_7d": 0.0,
        "cash_share_24h": 0.0, "cash_share_7d": 0.0, "inflow_outflow_ratio_24h": None,
        "avg_in_to_out_delay_s_24h": None, "tx_count_7d_to_30d": 10,
        "international_share_24h": 0.0,
    }


def engine(config=None) -> RuleEngine:
    return RuleEngine.from_config(config or CONFIG)


def fired(features: dict, config=None) -> set[str]:
    return {rule.rule_id for rule in engine(config).evaluate(features).fired_rules}


def test_benign_features_fire_nothing():
    result = engine().evaluate(benign())
    assert result.score == 0.0 and result.fired_rules == () and result.typology_hint is None


# --- R-STRUCT-01 --------------------------------------------------------------------------------

def structuring(count: int, cash: float = 1.0) -> dict:
    return {**benign(), "tx_count_7d": count + 2, "near_threshold_share_7d": count / (count + 2),
            "cash_share_7d": cash}


def test_structuring_positive_at_threshold_scores_half():
    p = PARAMS["structuring"]
    result = engine().evaluate(structuring(p["min_near_threshold_count_7d"]))
    assert [r.rule_id for r in result.fired_rules] == ["R-STRUCT-01"]
    assert result.score == pytest.approx(0.5)
    assert result.typology_hint == "structuring"


def test_structuring_saturates_at_configured_multiple():
    p = PARAMS["structuring"]
    count = int(p["min_near_threshold_count_7d"] * SATURATION)
    assert engine().evaluate(structuring(count)).score == pytest.approx(1.0)


def test_structuring_negative_too_few_near_threshold_operations():
    assert "R-STRUCT-01" not in fired(structuring(PARAMS["structuring"]["min_near_threshold_count_7d"] - 1))


def test_structuring_negative_not_cash():
    assert "R-STRUCT-01" not in fired(structuring(6, cash=PARAMS["structuring"]["min_cash_share_7d"] - 0.2))


# --- R-RAPID-01 ---------------------------------------------------------------------------------

def rapid(**override) -> dict:
    p = PARAMS["rapid_in_out"]
    base = {**benign(), "avg_in_to_out_delay_s_24h": p["max_avg_delay_s_24h"] / 4,
            "total_amount_24h_mad": p["min_total_amount_24h_mad"] * 3,
            "inflow_outflow_ratio_24h": 1.0}
    return {**base, **override}


def test_rapid_positive_and_faster_scores_higher():
    p = PARAMS["rapid_in_out"]
    slow = engine().evaluate(rapid(avg_in_to_out_delay_s_24h=p["max_avg_delay_s_24h"]))
    fast = engine().evaluate(rapid(avg_in_to_out_delay_s_24h=p["max_avg_delay_s_24h"] / 4))
    assert [r.rule_id for r in slow.fired_rules] == ["R-RAPID-01"]
    assert slow.score == pytest.approx(0.5) and fast.score > slow.score


@pytest.mark.parametrize("override", [
    {"avg_in_to_out_delay_s_24h": PARAMS["rapid_in_out"]["max_avg_delay_s_24h"] + 1},
    {"avg_in_to_out_delay_s_24h": None},
    {"total_amount_24h_mad": PARAMS["rapid_in_out"]["min_total_amount_24h_mad"] - 1},
    {"inflow_outflow_ratio_24h": PARAMS["rapid_in_out"]["min_inflow_outflow_ratio_24h"] - 0.01},
    {"inflow_outflow_ratio_24h": PARAMS["rapid_in_out"]["max_inflow_outflow_ratio_24h"] + 0.01},
    {"inflow_outflow_ratio_24h": None},
])
def test_rapid_negative(override):
    assert "R-RAPID-01" not in fired(rapid(**override))


# --- R-DORM-01 ----------------------------------------------------------------------------------

def dormant(**override) -> dict:
    p = PARAMS["dormant_then_active"]
    base = {**benign(), "tx_count_7d_to_30d": 0, "tx_count_7d": p["min_tx_count_7d"] + 2,
            "total_amount_7d_mad": p["min_total_amount_7d_mad"] * 2}
    return {**base, **override}


def test_dormant_positive():
    assert fired(dormant()) == {"R-DORM-01"}


@pytest.mark.parametrize("override", [
    {"tx_count_7d_to_30d": PARAMS["dormant_then_active"]["max_baseline_tx_count"] + 1},
    {"tx_count_7d": PARAMS["dormant_then_active"]["min_tx_count_7d"] - 1},
    {"total_amount_7d_mad": PARAMS["dormant_then_active"]["min_total_amount_7d_mad"] - 1},
    {"tx_count_7d_to_30d": None},  # extension feature missing (streaming v1): the rule stays silent
])
def test_dormant_negative(override):
    assert "R-DORM-01" not in fired(dormant(**override))


# --- R-CHAN-01 ----------------------------------------------------------------------------------

def channel(**override) -> dict:
    p = PARAMS["risky_channel"]
    base = {**benign(), "cash_share_24h": 1.0, "tx_count_24h": p["min_tx_count_24h"] + 1,
            "total_amount_24h_mad": p["min_total_amount_24h_mad"] * 1.5}
    return {**base, **override}


def test_channel_positive_cash_and_international():
    assert fired(channel()) == {"R-CHAN-01"}
    p = PARAMS["risky_channel"]
    international = channel(cash_share_24h=0.0, international_share_24h=p["min_risky_share_24h"] + 0.1)
    assert fired(international) == {"R-CHAN-01"}


@pytest.mark.parametrize("override", [
    {"cash_share_24h": PARAMS["risky_channel"]["min_risky_share_24h"] - 0.2},
    {"tx_count_24h": PARAMS["risky_channel"]["min_tx_count_24h"] - 1},
    {"total_amount_24h_mad": PARAMS["risky_channel"]["min_total_amount_24h_mad"] - 1},
    {"cash_share_24h": None},
])
def test_channel_negative(override):
    assert "R-CHAN-01" not in fired(channel(**override))


# --- configuration, interface, consistency ---------------------------------------------------

def test_thresholds_follow_the_configuration():
    config = copy.deepcopy(CONFIG)
    features = structuring(PARAMS["structuring"]["min_near_threshold_count_7d"])
    assert "R-STRUCT-01" in fired(features, config)
    config["rules"]["structuring"]["min_near_threshold_count_7d"] += 1
    assert "R-STRUCT-01" not in fired(features, config)
    config["rules"]["structuring"]["enabled"] = False
    assert "R-STRUCT-01" not in engine(config).rule_ids


def test_every_rule_has_a_french_description_and_configured_parameters():
    assert set(RULE_IDS) == set(DESCRIPTIONS)
    assert all(len(text) > 20 for text in DESCRIPTIONS.values())
    for section in ("structuring", "rapid_in_out", "dormant_then_active", "risky_channel"):
        assert "enabled" in PARAMS[section] and len(PARAMS[section]) >= 3


def test_reporting_threshold_is_configured_not_hard_coded():
    streaming = json.loads((ROOT / "config" / "streaming.json").read_text(encoding="utf-8"))
    assert CONFIG["reporting_threshold"] == streaming["reporting_threshold_mad"]
    literal = re.compile(r"\b100[_,]?000\b")
    offenders = [
        path.name for path in (ROOT / "src" / "aml" / "models").glob("*.py")
        if literal.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []


def test_output_matches_the_scoring_interface():
    result = engine().evaluate({**rapid(), **dormant(), **channel()})
    assert 0.0 <= result.score <= 1.0
    assert all(0.5 <= rule.score <= 1.0 for rule in result.fired_rules)
    assert result.score == max(rule.score for rule in result.fired_rules)
    explanation = result.explanation_fields()
    assert set(explanation) == {"fired_rules", "typology_hint"}
    assert all(set(item) == {"rule_id", "description"} for item in explanation["fired_rules"])
    versions = {"rules": engine().version}
    stamp = "2027-02-03T09:42:10Z"
    score = {"account_id": "acct-000123", "tx_id": "tx-00012345", "risk_score": result.score,
             "model_versions": versions, "ts": stamp}
    validate_score(score)
    validate_alert({**score, "explanation": {
        "summary_fr": "Règle déclenchée.", "top_features": [], "graph": None, **explanation}})


def test_batch_and_single_evaluation_agree():
    rng = np.random.default_rng(3)
    names = ("tx_count_24h", "tx_count_7d", "total_amount_24h_mad", "total_amount_7d_mad",
             "near_threshold_share_7d", "cash_share_24h", "cash_share_7d",
             "inflow_outflow_ratio_24h", "avg_in_to_out_delay_s_24h", "tx_count_7d_to_30d",
             "international_share_24h")
    columns = {
        "tx_count_24h": rng.integers(0, 12, 400), "tx_count_7d": rng.integers(0, 40, 400),
        "total_amount_24h_mad": rng.uniform(0, 4e5, 400), "total_amount_7d_mad": rng.uniform(0, 4e5, 400),
        "near_threshold_share_7d": rng.uniform(0, 1, 400), "cash_share_24h": rng.uniform(0, 1, 400),
        "cash_share_7d": rng.uniform(0, 1, 400), "inflow_outflow_ratio_24h": rng.uniform(0, 3, 400),
        "avg_in_to_out_delay_s_24h": rng.uniform(0, 8e4, 400), "tx_count_7d_to_30d": rng.integers(0, 6, 400),
        "international_share_24h": rng.uniform(0, 1, 400),
    }
    assert set(columns) == set(names)
    batch = engine().layer_score_columns(columns)
    for index in range(0, 400, 7):
        row = {name: float(values[index]) for name, values in columns.items()}
        assert engine().evaluate(row).score == pytest.approx(batch[index], abs=1e-6)
    assert Path(ROOT / "config" / "scoring.yaml").exists()
