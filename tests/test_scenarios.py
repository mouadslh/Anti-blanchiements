"""Tests de l'injection des scénarios AML (Phase 3) : génération, paramètres, niveaux, placement.

Les jeux de test utilisent une petite population (``POPULATION``) et une limite de taux de
comptes relevée : la contrainte < 1 % ne s'applique qu'aux profils ``light`` et ``full``.
"""

from __future__ import annotations

import functools
import itertools
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from aml.simulator.dataset import Dataset, generate_dataset
from aml.simulator.normal import START, _customer_events, _population
from aml.simulator.scenario_config import (
    DEFAULT_CONFIG,
    LEVELS,
    SCENARIOS,
    ScenarioConfigError,
    load_config,
    load_config_file,
    resolve_params,
)
from aml.simulator.scenarios import AccountPool, Context, build_layering, external_count

POPULATION = 600
T = DEFAULT_CONFIG["reporting_threshold"]
COMPANY_MEDIAN = 15000


def one_case(scenario: str, level: str, **params: Any) -> dict[str, Any]:
    """Configuration : un seul cas (``scenario``, ``level``), paramètres surchargés."""
    return {
        "max_account_rate": 1.0,
        "profiles": {"light": {"block_assignment": "any", "cases": {scenario: {level: 1}}}},
        "scenarios": {scenario: {"levels": {level: params}}} if params else {},
    }


@functools.cache
def run(scenario: str, level: str, seed: int = 42, params: tuple = ()) -> tuple[Any, ...]:
    config = one_case(scenario, level, **dict(params))
    return generate_dataset("light", seed, config, population_size=POPULATION)


def stamp(value: str) -> datetime:
    return datetime.fromisoformat(value)


def labeled_rows(scenario: str, level: str, seed: int = 42, params: tuple = ()
                 ) -> list[dict[str, Any]]:
    """Transactions « scénario » du cas, triées par instant puis identifiant."""
    events, labels, _ = run(scenario, level, seed, params)
    ids = {row["tx_id"] for row in labels if row["tx_id"]}
    return sorted((event for event in events if event["tx_id"] in ids),
                  key=lambda event: (event["timestamp"], event["tx_id"]))


def roles(scenario: str, level: str, seed: int = 42, params: tuple = ()) -> dict[str, str]:
    _, labels, _ = run(scenario, level, seed, params)
    return {row["account_id"]: row["role"] for row in labels if not row["tx_id"]}


# ------------------------------------------------------------------------ configuration

def test_default_yaml_matches_code() -> None:
    yaml = pytest.importorskip("yaml")
    path = Path(__file__).resolve().parents[1] / "config" / "simulator.yaml"
    assert yaml.safe_load(path.read_text(encoding="utf-8")) == DEFAULT_CONFIG


def test_default_config_is_valid_and_covers_all_levels() -> None:
    config = load_config()
    assert set(config["scenarios"]) == set(SCENARIOS)
    for scenario in SCENARIOS:
        assert set(config["scenarios"][scenario]["levels"]) == set(LEVELS)


@pytest.mark.parametrize(
    "overrides",
    [
        {"scenarios": {"structuring": {"base": {"window_days": 99}}}},  # hors plage
        {"scenarios": {"structuring": {"levels": {"low": {"n_cities": 2.5}}}}},  # entier attendu
        {"scenarios": {"layering": {"levels": {"low": {"hop_delay_minutes_range": [60, 5]}}}}},
        {"scenarios": {"mule": {"base": {"unknown_param": 1}}}},  # paramètre inconnu
        {"scenarios": {"mule": {"levels": {"extreme": {}}}}},  # niveau inconnu
        {"scenarios": {"smurfing": {"base": {}}}},  # scénario inconnu
        {"reporting_threshold": 0},
        {"max_account_rate": 0},
        {"profiles": {"light": {"block_assignment": "random"}}},
        {"profiles": {"light": {"cases": {"structuring": {"medium": -1}}}}},
        {"placement": {"blocks": {"test": [80, 120]}}},
    ],
)
def test_invalid_configuration_is_rejected(overrides: dict[str, Any]) -> None:
    with pytest.raises(ScenarioConfigError):
        load_config(overrides)


def test_pairs_are_sampled_once_per_case_and_ranges_are_kept() -> None:
    config = load_config()
    params = resolve_params(random.Random(1), config, "structuring", "high")
    assert 3 <= params["n_accounts_in_group"] <= 5
    assert params["amount_fraction_range"] == (0.5, 0.99)
    assert resolve_params(random.Random(1), config, "structuring", "high") == params


def test_yaml_file_overrides_are_merged_with_defaults(tmp_path: Path) -> None:
    pytest.importorskip("yaml")
    override = tmp_path / "override.yaml"
    override.write_text("reporting_threshold: 50000\nscenarios:\n  mule:\n    base:\n"
                        "      n_mules: 4\n", encoding="utf-8")
    config = load_config_file(override)
    assert config["reporting_threshold"] == 50000
    assert config["scenarios"]["mule"]["base"]["n_mules"] == 4
    assert config["scenarios"]["mule"]["base"]["n_destinations"] == 2  # défaut conservé


# ----------------------------------------------------------------------- fractionnement

def test_structuring_low_deposits_sit_just_under_threshold() -> None:
    rows = labeled_rows("structuring", "low")
    deposits = [row for row in rows if row["channel"] == "cash_deposit"]
    assert len(roles("structuring", "low")) == 2  # 1 compte fractionné + 1 collecteur
    assert len(deposits) == 10  # deposits_per_account x 1 compte
    assert all(0.90 * T <= row["amount"] <= 0.99 * T for row in deposits)
    assert all(row["target_account_id"] == "ext-cash" for row in deposits)
    assert len({row["city"] for row in deposits}) == 1  # n_cities = 1


def test_structuring_funds_are_consolidated_after_the_window() -> None:
    rows = labeled_rows("structuring", "low")
    deposits = [row for row in rows if row["channel"] == "cash_deposit"]
    (transfer,) = [row for row in rows if row["channel"] == "transfer"]
    assert roles("structuring", "low")[transfer["target_account_id"]] == "beneficiary"
    assert transfer["amount"] == pytest.approx(sum(row["amount"] for row in deposits), abs=0.1)
    first, last = stamp(deposits[0]["timestamp"]), stamp(deposits[-1]["timestamp"])
    assert last - first < timedelta(days=14)
    assert stamp(transfer["timestamp"]) - first >= timedelta(days=14 + 3)


def test_structuring_high_uses_more_accounts_and_mixes_normal_deposits() -> None:
    _, _, manifest = run("structuring", "high")
    case = manifest["cases"][0]
    assert case["accounts"] >= 4  # au moins 3 comptes fractionnés + collecteur
    assert case["camouflage_transactions"] > 0
    assert case["params"]["amount_fraction_range"] == [0.5, 0.99]


# ---------------------------------------------------------------------------- layering

def test_layering_chain_loses_the_fee_at_every_hop() -> None:
    params = (("international_exit_prob", 0.0), ("chain_length", 4))
    rows = labeled_rows("layering", "low", params=params)
    deposit, *hops = rows
    assert deposit["channel"] == "cash_deposit" and deposit["amount"] == T * 3
    assert len(hops) == 4 + 1  # chain_length intermédiaires => chain_length + 1 sauts
    assert all(row["channel"] == "transfer" for row in hops)
    for before, after in itertools.pairwise(hops):
        assert before["target_account_id"] == after["source_account_id"]
        assert after["amount"] == pytest.approx(before["amount"] * 0.99, abs=0.02)
    assert roles("layering", "low", params=params)[hops[0]["source_account_id"]] == "originator"
    assert len(roles("layering", "low", params=params)) == 1 + 4 + 1


def test_layering_low_delays_are_short_and_high_delays_are_long() -> None:
    def gaps_minutes(level: str) -> list[float]:
        rows = [row for row in labeled_rows("layering", level) if row["channel"] == "transfer"]
        arrival = {row["target_account_id"]: stamp(row["timestamp"]) for row in rows}
        return [(stamp(row["timestamp"]) - arrival[row["source_account_id"]]).total_seconds() / 60
                for row in rows if row["source_account_id"] in arrival]

    low, high = gaps_minutes("low"), gaps_minutes("high")
    assert low and high
    assert 0 <= min(low) and max(low) <= 60.1  # niveau faible : 5 à 60 min par saut
    assert max(high) > 360  # niveau élevé : jusqu'à 2 880 min par saut


def test_layering_branches_follow_the_level() -> None:
    no_exit = (("international_exit_prob", 0.0),)

    def beneficiary_inflows(level: str) -> int:
        (beneficiary,) = [account for account, role in roles("layering", level, params=no_exit).items()
                          if role == "beneficiary"]
        return sum(1 for row in labeled_rows("layering", level, params=no_exit)
                   if row["target_account_id"] == beneficiary)

    assert [beneficiary_inflows(level) for level in LEVELS] == [1, 2, 3]


def test_layering_international_exit_is_configurable() -> None:
    customers = _population(200, 42)
    context = Context(AccountPool(customers), 100_000.0, external_count(200))
    params = resolve_params(random.Random(1), load_config(), "layering", "low")
    for probability, expected in ((1.0, True), (0.0, False)):
        draft = build_layering(random.Random(5), context, "low",
                               {**params, "international_exit_prob": probability})
        exits = [event for event in draft.events if event.channel == "international_transfer"]
        assert bool(exits) is expected
        if exits:
            assert exits[0].target.startswith("ext-")
            assert draft.roles[exits[0].source.account_id] == "beneficiary"


# ----------------------------------------------------------------------- comptes relais

def test_mule_network_receives_then_forwards_quickly() -> None:
    rows = labeled_rows("mule", "low")
    mule_roles = roles("mule", "low")
    mules = {a for a, r in mule_roles.items() if r == "mule"}
    assert len(mules) == 8
    for mule in mules:
        inbound = [row for row in rows if row["target_account_id"] == mule]
        outbound = [row for row in rows if row["source_account_id"] == mule]
        assert len({row["source_account_id"] for row in inbound}) == 12  # sources distinctes
        received = sum(row["amount"] for row in inbound)
        assert sum(row["amount"] for row in outbound) == pytest.approx(received * 0.9, abs=0.1)
        delay = stamp(outbound[0]["timestamp"]) - max(stamp(row["timestamp"]) for row in inbound)
        assert timedelta(0) <= delay <= timedelta(hours=6.1)  # niveau faible : 0,5 à 6 h
        assert {row["channel"] for row in outbound} <= {"transfer", "cash_withdrawal"}
    destinations = {a for a, r in mule_roles.items() if r == "beneficiary"}
    assert 1 <= len(destinations) <= 2


def test_mule_cash_out_share_is_configurable() -> None:
    cash = labeled_rows("mule", "low", params=(("cash_out_share", 0.6),))
    none = labeled_rows("mule", "low", params=(("cash_out_share", 0.0),))
    assert any(row["channel"] == "cash_withdrawal" for row in cash)
    assert not any(row["channel"] == "cash_withdrawal" for row in none)


def test_mule_account_age_silences_earlier_normal_activity() -> None:
    events, labels, manifest = run("mule", "low")
    mules = {a for a, r in roles("mule", "low").items() if r == "mule"}
    case_start = START + timedelta(days=manifest["cases"][0]["start_day"] - 1)
    created = case_start - timedelta(days=60)  # account_age_days = 60
    labeled_ids = {row["tx_id"] for row in labels if row["tx_id"]}
    early = [event for event in events if event["source_account_id"] in mules
             and event["tx_id"] not in labeled_ids and stamp(event["timestamp"]) < created]
    assert early == []
    if created > START:  # sinon le compte existe déjà au début de la simulation
        assert manifest["rates"]["suppressed_normal_events"] > 0


# -------------------------------------------------------------------- flux circulaires

def test_round_tripping_closes_the_loop_with_a_small_loss() -> None:
    params = (("round_amount_share", 0.0), ("normal_mix_ratio", 0.0))
    rows = labeled_rows("round_tripping", "low", params=params)
    length, repeats = 3, 2
    assert len(rows) == length * repeats
    origin = rows[0]["source_account_id"]
    assert roles("round_tripping", "low", params=params)[origin] == "originator"
    assert rows[length - 1]["target_account_id"] == origin  # le premier tour revient à l'origine
    assert len({row["source_account_id"] for row in rows}) == length
    for row, following in itertools.pairwise(rows):
        assert row["target_account_id"] == following["source_account_id"]
    assert rows[length]["amount"] / rows[0]["amount"] == pytest.approx(0.98, abs=0.001)


def test_round_tripping_transfers_happen_on_business_days() -> None:
    for level in LEVELS:
        for row in labeled_rows("round_tripping", level):
            moment = stamp(row["timestamp"])
            assert moment.weekday() < 5 and 9 <= moment.hour < 17


def test_round_tripping_round_amount_share_follows_the_level() -> None:
    def round_share(level: str) -> float:
        rows = labeled_rows("round_tripping", level, params=(("n_repeats", 5),))
        return sum(row["amount"] % 1000 == 0 for row in rows) / len(rows)

    assert round_share("low") > round_share("high")


# --------------------------------------------------------------------- sociétés écran

def test_shell_companies_move_large_flows_through_few_counterparties() -> None:
    rows = labeled_rows("shell_company", "low")
    shells = {a for a, r in roles("shell_company", "low").items() if r == "shell_company"}
    assert len(shells) == 4
    inflows = [row for row in rows if row["target_account_id"] in shells
               and row["source_account_id"] not in shells]
    counterparties = {row["source_account_id"] for row in inflows}
    assert 2 <= len(counterparties) <= 3  # niveau faible : peu de contreparties
    per_shell = sum(row["amount"] for row in inflows) / len(shells)
    assert per_shell == pytest.approx(10 * COMPANY_MEDIAN, rel=0.001)
    outflows = [row for row in rows if row["source_account_id"] in shells]
    assert sum(row["amount"] for row in outflows) == pytest.approx(
        sum(row["amount"] for row in inflows), rel=0.06)  # entrées et sorties presque égales


def test_shell_low_has_no_payroll_or_facade_and_high_has_both() -> None:
    assert run("shell_company", "low")[2]["cases"][0]["camouflage_transactions"] == 0
    assert run("shell_company", "high")[2]["cases"][0]["camouflage_transactions"] > 0


def test_shell_dormancy_removes_normal_activity_before_the_peak() -> None:
    events, labels, manifest = run("shell_company", "low")
    shells = {a for a, r in roles("shell_company", "low").items() if r == "shell_company"}
    case_start = START + timedelta(days=manifest["cases"][0]["start_day"] - 1)
    labeled_ids = {row["tx_id"] for row in labels if row["tx_id"]}
    quiet = [event for event in events if event["source_account_id"] in shells
             and event["tx_id"] not in labeled_ids
             and case_start - timedelta(days=30) <= stamp(event["timestamp"]) < case_start]
    assert quiet == []
    assert manifest["rates"]["suppressed_normal_events"] > 0


# -------------------------------------------------- transverse : déterminisme et niveaux

def test_generation_is_deterministic_and_seed_dependent() -> None:
    first = run("layering", "medium", 42)
    again = generate_dataset("light", 42, one_case("layering", "medium"),
                             population_size=POPULATION)
    assert first[0] == again[0] and first[1] == again[1]
    other = run("layering", "medium", 7)
    assert [e["source_account_id"] for e in other[0]] != [e["source_account_id"] for e in first[0]]


def test_parameters_override_changes_the_generated_case() -> None:
    small = run("mule", "medium", params=(("n_mules", 3), ("n_inbound_sources", 5)))
    assert sum(1 for r in small[1] if not r["tx_id"] and r["role"] == "mule") == 3
    assert small[2]["cases"][0]["params"]["n_inbound_sources"] == 5


def test_cases_use_disjoint_accounts() -> None:
    config = {"max_account_rate": 1.0, "profiles": {"light": {"block_assignment": "any",
              "cases": {name: {"medium": 2} for name in SCENARIOS}}}}
    _, labels, manifest = generate_dataset("light", 42, config, population_size=1500)
    accounts = [row["account_id"] for row in labels if not row["tx_id"]]
    assert len(accounts) == len(set(accounts)) == manifest["rates"]["labeled_accounts"]
    assert len(manifest["cases"]) == 10


def test_stream_is_chronological_with_sequential_ids() -> None:
    events, _, _ = run("shell_company", "medium")
    assert [e["tx_id"] for e in events] == [f"tx-{i:08d}" for i in range(1, len(events) + 1)]
    stamps = [e["timestamp"] for e in events]
    assert stamps == sorted(stamps)


def test_account_rate_guard_rejects_oversized_scenarios() -> None:
    with pytest.raises(ScenarioConfigError, match="taux de comptes"):
        Dataset("light", 42, None, population_size=POPULATION)  # 5 cas / 600 clients > 1 %


# ----------------------------------------------------------------------------- placement

def planned(profile: str, overrides: dict[str, Any] | None = None) -> Dataset:
    config = {"max_account_rate": 1.0, **(overrides or {})}
    return Dataset(profile, 42, config, population_size=1500)


def test_full_profile_has_one_case_per_scenario_and_level() -> None:
    dataset = planned("full")
    assert sorted((c.draft.scenario, c.draft.level) for c in dataset.cases) == sorted(
        (scenario, level) for scenario in SCENARIOS for level in LEVELS)


def test_full_profile_assigns_one_case_per_block_per_scenario() -> None:
    dataset = planned("full")
    for scenario in SCENARIOS:
        assigned = [c.assigned_block for c in dataset.cases if c.draft.scenario == scenario]
        assert sorted(assigned) == ["test", "train", "validation"]


def test_cases_stay_inside_their_block_when_durations_allow() -> None:
    shorter = {"scenarios": {"structuring": {"base": {"window_days": 10}},
                             "round_tripping": {"base": {"period_days": 10}}}}
    dataset = planned("full", shorter)
    bounds = DEFAULT_CONFIG["placement"]["blocks"]
    for case in dataset.cases:
        assert case.block == case.assigned_block and case.fits_single_block
        first = min(moment for moment, _, _ in case.events)
        last = max(moment for moment, _, _ in case.events)
        low, high = bounds[case.block]
        assert START + timedelta(days=low - 1) <= first
        assert last < START + timedelta(days=high)


def test_too_long_cases_fall_back_and_are_reported() -> None:
    dataset = planned("full")  # défauts du catalogue : certains cas dépassent 16 jours
    assert any(c.block != c.assigned_block for c in dataset.cases)
    assert all(c.block != "cross" for c in dataset.cases)  # chacun tient dans un bloc


def test_case_longer_than_the_period_is_an_error() -> None:
    config = {"max_account_rate": 1.0,
              "placement": {"first_case_day": 80},
              "profiles": {"light": {"block_assignment": "any",
                                     "cases": {"round_tripping": {"high": 1}}}}}
    with pytest.raises(ScenarioConfigError, match="ne tient pas"):
        Dataset("light", 42, config, population_size=POPULATION)


# ------------------------------------------------- non-régression du simulateur normal

def test_normal_simulator_networks_always_include_an_external_merchant() -> None:
    customers = _population(POPULATION, 42)
    assert all(any(a.startswith("ext-") for a in c.counterparties) for c in customers)
    assert sum(len(_customer_events(c, 42)) for c in customers) > 0  # plus de TypeError
