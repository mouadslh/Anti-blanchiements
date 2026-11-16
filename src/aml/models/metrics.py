"""Evaluation metrics of docs/evaluation_plan.md (sections 3 to 5) on (account, day) units.

An event-level score is first reduced to one score per (account, day): the maximum over the day's
events (contract C-09). The alert unit is that pair. Nothing here reads a model: it only needs
scores and the ground-truth positives, so the same code judges rules, Isolation Forest and XGBoost.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import sqrt
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score

from aml.models.labels import positive_mask


def to_account_day(events: pd.DataFrame, score: np.ndarray, labels: pd.DataFrame) -> pd.DataFrame:
    """One row per (account, day): max score of the day and the ground-truth ``positive`` flag."""
    frame = pd.DataFrame(
        {"account_id": events["account_id"].to_numpy(), "day": events["day"].to_numpy(), "score": score}
    )
    daily = frame.groupby(["account_id", "day"], sort=True, observed=True)["score"].max().reset_index()
    daily["positive"] = positive_mask(daily["account_id"], daily["day"], labels)
    return daily


def wilson_interval(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """95 % Wilson interval of a proportion (plan 3.2); (0, 1) when there is no case."""
    if total == 0:
        return 0.0, 1.0
    p = successes / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    margin = z * sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return max(0.0, centre - margin), min(1.0, centre + margin)


def top_k_metrics(daily: pd.DataFrame, k: int) -> dict[str, float | int | None]:
    """Precision@k and recall@k per day, pooled (plan 3.1), with the ceiling of precision@k."""
    ordered = daily.sort_values(["day", "score", "account_id"], ascending=[True, False, True])
    total_alerts = total_tp = total_positive = 0
    ceiling_numerator = 0
    positive_days = 0
    per_day_precision: list[float] = []
    for _, group in ordered.groupby("day", sort=True):
        alerts = min(k, len(group))
        tp = int(group["positive"].to_numpy()[:alerts].sum())
        positives = int(group["positive"].sum())
        total_alerts += alerts
        total_tp += tp
        total_positive += positives
        ceiling_numerator += min(positives, alerts)
        per_day_precision.append(tp / alerts if alerts else 0.0)
        if positives:
            positive_days += 1
    precision = total_tp / total_alerts if total_alerts else None
    ceiling = ceiling_numerator / total_alerts if total_alerts else None
    return {
        "k": k,
        "precision_at_k": precision,
        "recall_at_k": total_tp / total_positive if total_positive else None,
        "precision_ceiling": ceiling,
        "precision_at_k_normalised": precision / ceiling if precision is not None and ceiling else None,
        "mean_daily_precision_at_k": float(np.mean(per_day_precision)) if per_day_precision else None,
        "days": len(per_day_precision),
        "days_with_positive": positive_days,
    }


def ranking_metrics(daily: pd.DataFrame) -> dict[str, float | int | None]:
    """PR-AUC (average precision), ROC-AUC and prevalence on (account, day) units (plan 3.3)."""
    labels = daily["positive"].to_numpy()
    positives = int(labels.sum())
    result: dict[str, float | int | None] = {
        "units": len(daily),
        "positive_units": positives,
        "prevalence": positives / len(daily) if len(daily) else None,
        "pr_auc": None,
        "roc_auc": None,
    }
    if 0 < positives < len(daily):
        result["pr_auc"] = float(average_precision_score(labels, daily["score"]))
        result["roc_auc"] = float(roc_auc_score(labels, daily["score"]))
    return result


def cases_in_block(labels: pd.DataFrame, first_day: int, last_day: int) -> pd.DataFrame:
    """Cases whose first labelled day falls in the block (the simulator places cases by start)."""
    starts = labels.groupby("case_id")["start_day"].min()
    kept = starts[(starts >= first_day) & (starts <= last_day)].index
    return labels[labels["case_id"].isin(kept)]


def case_best_scores(daily: pd.DataFrame, labels: pd.DataFrame, block_cases: pd.DataFrame) -> pd.DataFrame:
    """For each case of the block, its best (account, day) score during an active interval.

    A case is detected at threshold tau iff ``best_score >= tau`` (an alert on a day inside the
    account's own interval, plan section 1). Cases with no scored positive unit get ``-inf``.
    """
    positives = daily[daily["positive"]]
    owner = block_cases[["account_id", "case_id"]].drop_duplicates("account_id")
    joined = positives.merge(owner, on="account_id", how="inner")
    best = joined.groupby("case_id")["score"].max()
    info = (
        block_cases.groupby("case_id")
        .agg(
            scenario=("scenario", "first"),
            sophistication=("sophistication", "first"),
            start_day=("start_day", "min"),
            end_day=("end_day", "max"),
            accounts=("account_id", "nunique"),
        )
        .reset_index()
    )
    info["best_score"] = info["case_id"].map(best).fillna(-np.inf)
    return info


@dataclass(frozen=True)
class CostParams:
    c_fp: float = 1.0
    c_fn: float = 200.0


def operating_point(
    daily: pd.DataFrame, cases: pd.DataFrame, threshold: float, costs: CostParams, n_days: int
) -> dict[str, float | int | None]:
    """Counts and cost at one threshold (plan 5.1): FP = false alerts, FN = missed cases."""
    alerted = daily["score"].to_numpy() >= threshold
    positive = daily["positive"].to_numpy()
    true_alerts = int((alerted & positive).sum())
    false_alerts = int((alerted & ~positive).sum())
    detected = int((cases["best_score"].to_numpy() >= threshold).sum())
    missed = len(cases) - detected
    positive_units = int(positive.sum())
    return {
        "threshold": float(threshold),
        "alerts": int(alerted.sum()),
        "alerts_per_day": float(alerted.sum()) / n_days if n_days else None,
        "true_alerts": true_alerts,
        "false_alerts": false_alerts,
        "precision": true_alerts / int(alerted.sum()) if alerted.sum() else None,
        "recall_units": true_alerts / positive_units if positive_units else None,
        "cases": len(cases),
        "cases_detected": detected,
        "cases_missed": missed,
        "cost": costs.c_fp * false_alerts + costs.c_fn * missed,
    }


def candidate_thresholds(daily: pd.DataFrame, cases: pd.DataFrame, grid: int = 2001) -> np.ndarray:
    """Thresholds worth trying: a fine quantile grid of the scores, the case scores, and +inf."""
    scores = daily["score"].to_numpy()
    quantiles = np.quantile(scores, np.linspace(0.0, 1.0, grid)) if len(scores) else np.array([])
    case_scores = cases["best_score"].to_numpy()
    case_scores = case_scores[np.isfinite(case_scores)]
    return np.unique(np.concatenate([quantiles, case_scores, [np.inf]]))


def choose_threshold(
    daily: pd.DataFrame,
    cases: pd.DataFrame,
    costs: CostParams,
    k_alerts_per_day: float,
    n_days: int,
) -> dict[str, Any]:
    """Validation rule of plan 5.4.

    Among the thresholds whose *average* number of alerts per day does not exceed ``k``, keep the
    one with the lowest cost ``c_fp * FP + c_fn * FN``; on equal cost keep the highest threshold
    (fewest alerts). Must be called on the validation block only (rule L-7).
    """
    best: dict[str, Any] | None = None
    for threshold in candidate_thresholds(daily, cases):
        point = operating_point(daily, cases, float(threshold), costs, n_days)
        if point["alerts_per_day"] is not None and point["alerts_per_day"] > k_alerts_per_day:
            continue
        key = (point["cost"], -float(threshold))
        if best is None or key < (best["cost"], -best["threshold"]):
            best = point
    assert best is not None  # threshold +inf raises no alert, hence is always feasible
    return best


def cost_curve(
    daily: pd.DataFrame,
    cases: pd.DataFrame,
    ratios: Sequence[float],
    c_fp: float,
    n_days: int,
    k_alerts_per_day: float,
) -> dict[str, dict[str, Any]]:
    """Best feasible threshold for each cost ratio r = c_fn / c_fp (sensitivity, plan 5.3)."""
    return {
        str(ratio): choose_threshold(
            daily, cases, CostParams(c_fp, c_fp * ratio), k_alerts_per_day, n_days
        )
        for ratio in ratios
    }


def detection_by_group(cases: pd.DataFrame, threshold: float) -> dict[str, Any]:
    """Cases detected per scenario and per sophistication level, with Wilson intervals."""
    detected = cases["best_score"].to_numpy() >= threshold
    table = cases.assign(detected=detected)
    result: dict[str, Any] = {}
    for column in ("scenario", "sophistication"):
        groups = {}
        for name, group in table.groupby(column):
            hits, total = int(group["detected"].sum()), len(group)
            low, high = wilson_interval(hits, total)
            groups[str(name)] = {
                "detected": hits,
                "cases": total,
                "recall": hits / total,
                "wilson_95": [round(low, 4), round(high, 4)],
            }
        result[column] = groups
    return result


def evaluate_block(
    daily: pd.DataFrame,
    cases: pd.DataFrame,
    threshold: float,
    *,
    costs: CostParams,
    k: int,
    n_days: int,
) -> dict[str, Any]:
    """All metrics of one block at a threshold that was chosen elsewhere (on validation)."""
    return {
        "ranking": ranking_metrics(daily),
        "top_k": top_k_metrics(daily, k),
        "operating_point": operating_point(daily, cases, threshold, costs, n_days),
        "detection": detection_by_group(cases, threshold),
        "cases": [
            {
                "case_id": row.case_id,
                "scenario": row.scenario,
                "sophistication": row.sophistication,
                "best_score": None if not np.isfinite(row.best_score) else round(float(row.best_score), 6),
                "detected": bool(row.best_score >= threshold),
            }
            for row in cases.itertuples(index=False)
        ],
    }
