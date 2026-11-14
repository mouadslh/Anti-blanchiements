"""Constructeurs des cinq scénarios AML décrits dans ``docs/typologies.md`` (section 4).

Chaque constructeur retourne un ``Draft`` : des événements datés **relativement** au début du
cas, les rôles des comptes impliqués et d'éventuelles fenêtres de silence du comportement
normal. Le placement dans la période de 90 jours et l'attribution des ``tx_id`` sont faits
plus tard par ``aml.simulator.dataset``. Aucun champ de label n'est jamais ajouté à un
événement : la vérité terrain reste dans les ``Draft`` puis dans les fichiers de labels.

Convention de direction des flux : ``docs/specification_technique_aml.md`` C-05. La source
d'un événement est toujours un client ``acct-`` ; un dépôt d'espèces a pour cible ``ext-cash``.
"""

from __future__ import annotations

import itertools
import math
import random
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from aml.simulator.normal import CITIES, PROFILES, Customer, _weighted_choice
from aml.simulator.scenario_config import ScenarioConfigError

CASH_COUNTERPARTY = "ext-cash"
EXTERNAL_SHARE = 0.2  # H-13 : réservoir de comptes externes = 20 % des clients
SNAP_ALLOWANCE = timedelta(days=3, hours=12)  # borne du report au prochain jour ouvré
MAX_AMOUNT = 10_000_000_000.00
SALARY_MEDIAN = 6000.0  # médiane du salaire de simulator_assumptions.md (section 3.4)
SALARY_SIGMA = 0.4


@dataclass(frozen=True)
class Ev:
    """Événement relatif au début du cas (``offset`` >= 0)."""

    offset: timedelta
    source: Customer
    target: str
    amount: float
    channel: str
    city: str
    labeled: bool = True  # False : camouflage (activité normale mêlée), non étiqueté
    business: bool = False  # True : ramené aux jours ouvrés, 9 h - 17 h


@dataclass(frozen=True)
class Quiet:
    """Fenêtre où l'activité normale d'un compte est supprimée (relative au début du cas)."""

    account_id: str
    start: timedelta | None  # None : depuis le début de la simulation
    end: timedelta


@dataclass
class Draft:
    scenario: str
    level: str
    params: dict[str, Any]
    roles: dict[str, str]
    events: list[Ev]
    quiet: list[Quiet] = field(default_factory=list)

    def span(self) -> timedelta:
        """Borne supérieure de la durée du cas (report aux jours ouvrés compris)."""
        if not self.events:
            return timedelta(0)
        longest = max(event.offset for event in self.events)
        if any(event.business for event in self.events):
            longest += SNAP_ALLOWANCE
        return longest


class AccountPool:
    """Attribue des comptes clients disjoints : un compte sert au plus un cas."""

    def __init__(self, customers: list[Customer]) -> None:
        self._customers = customers
        self._used: set[str] = set()

    def take(self, rng: random.Random, count: int, profiles: tuple[str, ...] | None = None
             ) -> list[Customer]:
        candidates = [
            customer for customer in self._customers
            if customer.account_id not in self._used
            and (profiles is None or customer.profile in profiles)
        ]
        if len(candidates) < count:
            raise ScenarioConfigError(
                f"population trop petite : {count} compte(s) {profiles or 'quelconques'} "
                f"demandés, {len(candidates)} disponibles"
            )
        chosen = rng.sample(candidates, count)
        self._used.update(customer.account_id for customer in chosen)
        return chosen


@dataclass
class Context:
    pool: AccountPool
    threshold: float
    n_external: int

    def external(self, rng: random.Random) -> str:
        return f"ext-{rng.randint(1, self.n_external):06d}"


def external_count(n_customers: int) -> int:
    return max(1, math.ceil(n_customers * EXTERNAL_SHARE))


def _amount(value: float) -> float:
    return round(float(min(max(value, 0.01), MAX_AMOUNT)), 2)


def _clock(rng: random.Random, first_hour: int = 8, last_hour: int = 18) -> timedelta:
    return timedelta(hours=rng.randrange(first_hour, last_hour), minutes=rng.randrange(60),
                     seconds=rng.randrange(60))


def _share_mix(count: int, ratio: float) -> int:
    """Nombre d'événements de camouflage pour que ``ratio`` de l'activité soit « normale »."""
    if ratio <= 0 or count <= 0:
        return 0
    return round(count * ratio / (1 - ratio))


def _cities(rng: random.Random, count: int) -> list[str]:
    remaining = list(CITIES)
    chosen: list[str] = []
    for _ in range(count):
        name = _weighted_choice(rng, remaining)
        chosen.append(name)
        remaining = [item for item in remaining if item[0] != name]
    return chosen


def _ordinary(rng: random.Random, customer: Customer, count: int, horizon: timedelta, *,
              business: bool = False, channels: frozenset[str] | None = None) -> list[Ev]:
    """Événements d'allure normale (loi de montants et canaux du profil du client)."""
    profile = PROFILES[customer.profile]
    options = [(name, weight) for name, weight in profile["channels"].items()
               if channels is None or name in channels]
    externals = [item for item in customer.counterparties if item.startswith("ext-")]
    events: list[Ev] = []
    for _ in range(count):
        channel = _weighted_choice(rng, options)
        if channel in {"cash_deposit", "cash_withdrawal"}:
            target = CASH_COUNTERPARTY
        elif channel == "card":
            target = rng.choice(externals or ["ext-000001"])
        else:
            target = rng.choice(customer.counterparties)
        amount = _amount(rng.lognormvariate(math.log(profile["median"]), profile["sigma"]))
        offset = timedelta(seconds=rng.uniform(0, max(horizon.total_seconds(), 1.0)))
        events.append(Ev(offset, customer, target, amount, channel, customer.city,
                         labeled=False, business=business))
    return events


# --------------------------------------------------------------------------- fractionnement

def build_structuring(rng: random.Random, ctx: Context, level: str, p: dict[str, Any]) -> Draft:
    """Dépôts en espèces juste sous T répartis sur plusieurs comptes, puis regroupement."""
    low, high = p["amount_fraction_range"]
    smurfs = ctx.pool.take(rng, p["n_accounts_in_group"], ("salaried", "student"))
    collector = ctx.pool.take(rng, 1)[0]
    cities = _cities(rng, p["n_cities"])
    events: list[Ev] = []
    deposited = {smurf.account_id: 0.0 for smurf in smurfs}
    for smurf in smurfs:
        for _ in range(p["deposits_per_account"]):
            amount = _amount(ctx.threshold * rng.uniform(low, high))
            offset = timedelta(days=rng.randrange(p["window_days"])) + _clock(rng)
            events.append(Ev(offset, smurf, CASH_COUNTERPARTY, amount, "cash_deposit",
                             rng.choice(cities)))
            deposited[smurf.account_id] += amount
    structured = len(events)
    for _ in range(_share_mix(structured, p["normal_mix_ratio"])):
        smurf = rng.choice(smurfs)
        profile = PROFILES[smurf.profile]
        offset = timedelta(days=rng.randrange(p["window_days"])) + _clock(rng)
        amount = _amount(rng.lognormvariate(math.log(profile["median"]), profile["sigma"]))
        events.append(Ev(offset, smurf, CASH_COUNTERPARTY, amount, "cash_deposit", smurf.city,
                         labeled=False))
    for smurf in smurfs:
        offset = timedelta(days=p["window_days"] + p["consolidation_delay_days"]) + _clock(rng)
        events.append(Ev(offset, smurf, collector.account_id, _amount(deposited[smurf.account_id]),
                         "transfer", smurf.city))
    roles = {smurf.account_id: "depositor" for smurf in smurfs}
    roles[collector.account_id] = "beneficiary"
    return Draft("structuring", level, p, roles, events)


# ------------------------------------------------------------------------------- layering

def build_layering(rng: random.Random, ctx: Context, level: str, p: dict[str, Any]) -> Draft:
    """Dépôt initial, chaînes parallèles de comptes de passage avec commission, sortie."""
    low, high = p["hop_delay_minutes_range"]
    fee = p["fee_rate_per_hop"]
    source = ctx.pool.take(rng, 1)[0]
    chains = [ctx.pool.take(rng, p["chain_length"]) for _ in range(p["n_parallel_branches"])]
    beneficiary = ctx.pool.take(rng, 1)[0]
    total = _amount(ctx.threshold * p["initial_amount_multiple"])
    start = _clock(rng)
    events = [Ev(start, source, CASH_COUNTERPARTY, total, "cash_deposit", source.city)]
    weights = [rng.uniform(0.8, 1.2) for _ in chains]
    received = 0.0
    last = start
    for chain, weight in zip(chains, weights, strict=True):
        amount = total * weight / sum(weights)
        moment = start
        path = [source, *chain, beneficiary]
        for sender, receiver in itertools.pairwise(path):
            moment += timedelta(minutes=rng.uniform(low, high))
            events.append(Ev(moment, sender, receiver.account_id, _amount(amount), "transfer",
                             sender.city))
            hop_amount = _amount(amount)
            amount *= 1 - fee  # commission prélevée à chaque saut
        received += hop_amount
        last = max(last, moment)
    if rng.random() < p["international_exit_prob"]:
        moment = last + timedelta(minutes=rng.uniform(low, high))
        events.append(Ev(moment, beneficiary, ctx.external(rng), _amount(received * (1 - fee)),
                         "international_transfer", beneficiary.city))
    roles = {source.account_id: "originator", beneficiary.account_id: "beneficiary"}
    roles.update({member.account_id: "intermediary" for chain in chains for member in chain})
    return Draft("layering", level, p, roles, events)


# ---------------------------------------------------------------------------- comptes relais

def build_mule(rng: random.Random, ctx: Context, level: str, p: dict[str, Any]) -> Draft:
    """Virements entrants multiples, retransmission rapide (virement ou retrait d'espèces)."""
    low, high = p["forward_delay_hours_range"]
    mules = ctx.pool.take(rng, p["n_mules"], ("student", "salaried"))
    destinations = ctx.pool.take(rng, p["n_destinations"], ("salaried", "merchant"))
    funders = ctx.pool.take(rng, p["n_mules"] * p["n_inbound_sources"])
    window = timedelta(days=p["inbound_window_days"])
    events: list[Ev] = []
    quiet: list[Quiet] = []
    for index, mule in enumerate(mules):
        mule_events: list[Ev] = []
        senders = funders[index * p["n_inbound_sources"]:(index + 1) * p["n_inbound_sources"]]
        for sender in senders:
            amount = _amount(max(100.0, rng.lognormvariate(math.log(p["inbound_amount_median"]), 0.5)))
            offset = timedelta(seconds=rng.uniform(0, window.total_seconds()))
            mule_events.append(Ev(offset, sender, mule.account_id, amount, "transfer", sender.city))
        received = sum(event.amount for event in mule_events)
        last_in = max(event.offset for event in mule_events)
        forwarded = received * p["forward_ratio"]
        cash = forwarded * p["cash_out_share"]
        if cash > 0:
            mule_events.append(Ev(last_in + timedelta(hours=rng.uniform(low, high)), mule,
                                  CASH_COUNTERPARTY, _amount(cash), "cash_withdrawal", mule.city))
        chosen = rng.sample(destinations, rng.randint(1, len(destinations)))
        parts = [rng.uniform(0.5, 1.5) for _ in chosen]
        for destination, part in zip(chosen, parts, strict=True):
            share = (forwarded - cash) * part / sum(parts)
            mule_events.append(Ev(last_in + timedelta(hours=rng.uniform(low, high)), mule,
                                  destination.account_id, _amount(share), "transfer", mule.city))
        horizon = max(event.offset for event in mule_events)
        events.extend(mule_events)
        events.extend(_ordinary(rng, mule, _share_mix(len(mule_events), p["normal_mix_ratio"]),
                                horizon))
        # Compte récent : pas d'activité avant son ouverture simulée (account_age_days).
        quiet.append(Quiet(mule.account_id, None, -timedelta(days=p["account_age_days"])))
    roles = {mule.account_id: "mule" for mule in mules}
    roles.update({destination.account_id: "beneficiary" for destination in destinations})
    return Draft("mule", level, p, roles, events, quiet)


# -------------------------------------------------------------------------- flux circulaires

def build_round_tripping(rng: random.Random, ctx: Context, level: str, p: dict[str, Any]) -> Draft:
    """Cycle de virements entre sociétés revenant à l'origine avec une perte par tour."""
    length = p["cycle_length"]
    n_companies = min(p["n_companies_in_loop"], length)
    companies = ctx.pool.take(rng, n_companies, ("company",))
    others = ctx.pool.take(rng, length - n_companies, ("merchant",)) if length > n_companies else []
    origin = companies[0]
    rest = [*companies[1:], *others]
    rng.shuffle(rest)
    cycle = [origin, *rest]
    steps = length * p["n_repeats"]
    factor = (1 - p["loss_per_loop"]) ** (1 / length)
    gaps = [max(1 / 48, p["loop_delay_days"] * rng.uniform(0.5, 1.5)) for _ in range(steps - 1)]
    scale = min(1.0, p["period_days"] / sum(gaps)) if gaps else 1.0
    base = ctx.threshold * p["initial_amount_multiple"]
    moment = _clock(rng, 9, 17)
    events: list[Ev] = []
    for step in range(steps):
        amount = base * factor ** step
        if amount >= 1000 and rng.random() < p["round_amount_share"]:
            amount = round(amount / 1000) * 1000  # facture « ronde » (H-06)
        sender, receiver = cycle[step % length], cycle[(step + 1) % length]
        events.append(Ev(moment, sender, receiver.account_id, _amount(amount), "transfer",
                         sender.city, business=True))
        if step < steps - 1:
            moment += timedelta(days=gaps[step] * scale)
    horizon = max(event.offset for event in events)
    for _ in range(_share_mix(steps, p["normal_mix_ratio"])):
        events.extend(_ordinary(rng, rng.choice(cycle), 1, horizon, business=True,
                                channels=frozenset({"transfer"})))
    roles = {member.account_id: "intermediary" for member in cycle}
    roles[origin.account_id] = "originator"
    return Draft("round_tripping", level, p, roles, events)


# ---------------------------------------------------------------------------- sociétés écran

def build_shell_company(rng: random.Random, ctx: Context, level: str, p: dict[str, Any]) -> Draft:
    """Sociétés dormantes puis gros flux de transit, avec peu de contreparties."""
    shells = ctx.pool.take(rng, p["n_shells"], ("company",))
    counterparties = ctx.pool.take(rng, p["n_distinct_counterparties"], ("company", "merchant"))
    employees = ctx.pool.take(rng, 3, ("salaried",)) if p["payroll_like_outflow_share"] > 0 else []
    median = PROFILES["company"]["median"]
    n_inflows = max(2 * p["n_distinct_counterparties"], 4)
    active = timedelta(days=p["active_days"])
    events: list[Ev] = []
    quiet: list[Quiet] = []
    for index, shell in enumerate(shells):
        weights = [rng.uniform(0.5, 1.5) for _ in range(n_inflows)]
        total_in = p["inflow_multiple"] * median
        for number, weight in enumerate(weights):
            sender = counterparties[(index + number) % len(counterparties)]
            received_at = timedelta(days=rng.randrange(p["active_days"])) + _clock(rng, 9, 17)
            amount = _amount(total_in * weight / sum(weights))
            events.append(Ev(received_at, sender, shell.account_id, amount, "transfer",
                             sender.city, business=True))
            sent_at = min(received_at + timedelta(hours=rng.uniform(1, 24)), active + timedelta(days=1))
            out_amount = _amount(amount * rng.uniform(0.95, 0.99))
            if rng.random() < p["international_share"]:
                events.append(Ev(sent_at, shell, ctx.external(rng), out_amount,
                                 "international_transfer", shell.city, business=True))
            else:
                other = rng.choice([item for item in shells if item is not shell])
                events.append(Ev(sent_at, shell, other.account_id, out_amount, "transfer",
                                 shell.city, business=True))
        for _ in range(_share_mix(n_inflows, p["payroll_like_outflow_share"])):
            employee = rng.choice(employees)
            offset = timedelta(days=rng.randrange(p["active_days"])) + _clock(rng, 9, 17)
            amount = _amount(rng.lognormvariate(math.log(SALARY_MEDIAN), SALARY_SIGMA))
            events.append(Ev(offset, shell, employee.account_id, amount, "transfer", shell.city,
                             labeled=False, business=True))
        for _ in range(_share_mix(n_inflows, p["facade_activity_ratio"])):
            offset = timedelta(days=rng.randrange(p["active_days"])) + _clock(rng)
            amount = _amount(rng.lognormvariate(math.log(p["facade_amount_median"]), 0.6))
            events.append(Ev(offset, shell, ctx.external(rng), amount, "card", shell.city,
                             labeled=False))
        if p["dormancy_days"] > 0:
            quiet.append(Quiet(shell.account_id, -timedelta(days=p["dormancy_days"]), timedelta(0)))
    roles = {shell.account_id: "shell_company" for shell in shells}
    return Draft("shell_company", level, p, roles, events, quiet)


BUILDERS: Mapping[str, Callable[[random.Random, Context, str, dict[str, Any]], Draft]] = {
    "structuring": build_structuring,
    "layering": build_layering,
    "mule": build_mule,
    "round_tripping": build_round_tripping,
    "shell_company": build_shell_company,
}
