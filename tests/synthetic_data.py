"""Small seeded transaction generator used by the model tests (not the project simulator)."""

from __future__ import annotations

import numpy as np
import pandas as pd

ORIGIN = pd.Timestamp("2027-01-15", tz="UTC")
COLUMNS = ["tx_id", "timestamp", "source_account_id", "target_account_id", "amount", "channel", "city"]


def make_transactions(
    seed: int = 0,
    n_accounts: int = 12,
    days: int = 40,
    threshold: float = 100_000.0,
    extra: list[dict] | None = None,
) -> pd.DataFrame:
    """Mixed channels, same-second collisions, idle gaps and near-threshold amounts."""
    rng = np.random.default_rng(seed)
    accounts = [f"acct-{i:06d}" for i in range(1, n_accounts + 1)]
    externals = [f"ext-{i:06d}" for i in range(1, 6)]
    cities = ["Casablanca", "Rabat", "Tanger"]
    rows: list[dict] = []
    for day in range(days):
        for _ in range(int(rng.integers(n_accounts, 3 * n_accounts))):
            channel = str(rng.choice(
                ["transfer", "card", "cash_deposit", "cash_withdrawal", "international_transfer"],
                p=[0.4, 0.25, 0.15, 0.1, 0.1],
            ))
            source = str(rng.choice(accounts[:-1]))  # the last account stays idle for 20 days
            if channel in ("cash_deposit", "cash_withdrawal"):
                target = "ext-cash"
            elif channel == "international_transfer":
                target = str(rng.choice(externals))
            else:
                target = str(rng.choice([a for a in accounts + externals if a != source]))
            amount = round(float(rng.lognormal(6, 1)), 2)
            if channel == "cash_deposit" and rng.random() < 0.2:
                amount = round(float(rng.uniform(0.9, 0.99) * threshold), 2)
            seconds = int(rng.integers(0, 86_400))
            if rng.random() < 0.05:
                seconds = 3_600 * 10  # force same-second collisions
            rows.append({
                "timestamp": ORIGIN + pd.Timedelta(days=day, seconds=seconds),
                "source_account_id": source, "target_account_id": target,
                "amount": amount, "channel": channel, "city": str(rng.choice(cities)),
            })
    for burst in range(8):  # the idle account becomes active on day 25
        rows.append({
            "timestamp": ORIGIN + pd.Timedelta(days=25, hours=burst),
            "source_account_id": accounts[-1], "target_account_id": "ext-cash",
            "amount": round(0.95 * threshold, 2), "channel": "cash_deposit", "city": "Rabat",
        })
    rows.extend(extra or [])
    frame = pd.DataFrame(rows).sort_values(["timestamp", "source_account_id"]).reset_index(drop=True)
    frame["tx_id"] = [f"tx-{i:08d}" for i in range(1, len(frame) + 1)]
    frame["timestamp"] = frame["timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return frame[COLUMNS]
