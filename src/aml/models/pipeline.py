"""Offline pipeline: features -> temporal split -> rules / Isolation Forest / XGBoost -> metrics.

Order of operations (docs/evaluation_plan.md, section 8):

1. features of every account event (backward windows only);
2. strict temporal split: the models are fitted on the training block, every choice (number of
   XGBoost trees, alert threshold) is made on the validation block, the test block is scored once;
3. a report with only numbers computed by this run.

``python manage.py train --profile full --seed 1`` calls :func:`run_baseline`.
"""

from __future__ import annotations

import json
import platform
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import sklearn
import xgboost

from aml.models.config import load_scoring_config
from aml.models.features import MODEL_FEATURES, FeatureParams, build_event_features
from aml.models.isolation_forest import IsolationForestLayer
from aml.models.labels import load_account_labels, positive_mask
from aml.models.metrics import (
    CostParams,
    case_best_scores,
    cases_in_block,
    choose_threshold,
    cost_curve,
    evaluate_block,
    to_account_day,
)
from aml.models.rules import RuleEngine
from aml.models.splits import TemporalSplit, assert_chronological
from aml.models.xgboost_layer import XGBoostLayer

TRANSACTION_COLUMNS = (
    "tx_id", "timestamp", "source_account_id", "target_account_id", "amount", "channel", "city",
)
LAYERS = ("rules", "isolation_forest", "xgboost")


def read_transactions(path: str | Path) -> pd.DataFrame:
    """Read a transactions CSV (labels are in a separate file and are not read here)."""
    return pd.read_csv(
        path,
        usecols=list(TRANSACTION_COLUMNS),
        dtype={"tx_id": str, "timestamp": str, "source_account_id": str, "target_account_id": str,
               "channel": "category", "city": "category"},
    )


def select_training_rows(events: pd.DataFrame, split: TemporalSplit) -> np.ndarray:
    """Rows allowed to fit the models: the training block only (not warm-up, validation, test)."""
    return split.mask(events["day"], "train")


def training_labels(
    events: pd.DataFrame, labels: pd.DataFrame, split: TemporalSplit
) -> np.ndarray:
    """Event labels for the training block, censored at the last training day (rule L-5)."""
    return positive_mask(
        events["account_id"], events["day"], labels, known_until_day=split.last_day("train")
    )


def _matrix(events: pd.DataFrame) -> np.ndarray:
    return events[list(MODEL_FEATURES)].to_numpy(dtype=np.float32)


def _rule_columns(events: pd.DataFrame) -> dict[str, np.ndarray]:
    return {name: events[name].to_numpy(dtype=float) for name in events.columns if name in MODEL_FEATURES}


def _block_frame(
    events: pd.DataFrame,
    layer_scores: Mapping[str, np.ndarray],
    labels: pd.DataFrame,
    block_cases: pd.DataFrame,
) -> dict[str, tuple[pd.DataFrame, pd.DataFrame]]:
    """Per layer: the (account, day) frame and the best-score table of the block's cases."""
    result = {}
    for layer, scores in layer_scores.items():
        daily = to_account_day(events, scores, labels)
        result[layer] = (daily, case_best_scores(daily, labels, block_cases))
    return result


def run_baseline(
    transactions_path: str | Path,
    labels_path: str | Path,
    *,
    seed: int,
    profile: str,
    scoring_config: Mapping[str, Any] | None = None,
    artifacts_dir: str | Path | None = None,
    origin: pd.Timestamp | None = None,
) -> dict[str, Any]:
    """Train the three layers on the training block and evaluate them; return the report."""
    started = time.time()
    config = dict(scoring_config or load_scoring_config())
    split = TemporalSplit.from_config(config)
    evaluation = config["evaluation"]
    k = int(evaluation["k_alerts_per_day"])
    costs = CostParams(float(evaluation["costs"]["c_fp"]), float(evaluation["costs"]["c_fn"]))
    model_seed = int(config["models"]["random_seed"]) + int(seed)

    transactions = read_transactions(transactions_path)
    if origin is None:
        from aml.simulator.normal import START

        origin = pd.Timestamp(START)
    timings: dict[str, float] = {}

    tick = time.time()
    events = build_event_features(transactions, FeatureParams.from_config(config), origin=origin)
    n_transactions = len(transactions)
    del transactions
    timings["features_s"] = round(time.time() - tick, 1)
    labels = load_account_labels(str(labels_path), origin)

    assert_chronological(events, split)
    events = events[events["day"] > split.warmup[1]].reset_index(drop=True)  # warm-up: history only
    train_mask = select_training_rows(events, split)
    val_mask = split.mask(events["day"], "validation")
    test_mask = split.mask(events["day"], "test")
    train, val, test = events[train_mask], events[val_mask], events[test_mask]

    y_train = training_labels(train, labels, split)
    y_val = positive_mask(val["account_id"], val["day"], labels)
    data_summary = {
        "transactions": n_transactions,
        "account_events_scored": len(events),
        "labelled_accounts": int(labels["account_id"].nunique()),
        "cases": int(labels["case_id"].nunique()),
        "blocks": {
            name: {
                "days": list(split.range_of(name)),
                "events": int(mask.sum()),
                "positive_events": int(positive_mask(
                    events.loc[mask, "account_id"], events.loc[mask, "day"], labels,
                    known_until_day=split.last_day("train") if name == "train" else None,
                ).sum()),
            }
            for name, mask in (("train", train_mask), ("validation", val_mask), ("test", test_mask))
        },
    }

    # --- Fit (training block only) ---
    tick = time.time()
    engine = RuleEngine.from_config(config)
    forest = IsolationForestLayer(config["models"]["isolation_forest"], model_seed, MODEL_FEATURES)
    forest.fit(_matrix(train))
    timings["isolation_forest_fit_s"] = round(time.time() - tick, 1)
    tick = time.time()
    booster = XGBoostLayer(config["models"]["xgboost"], model_seed, MODEL_FEATURES)
    booster.fit(_matrix(train), y_train, validation=(_matrix(val), y_val))
    timings["xgboost_fit_s"] = round(time.time() - tick, 1)
    del train

    def layer_scores(frame: pd.DataFrame) -> dict[str, np.ndarray]:
        matrix = _matrix(frame)
        return {
            "rules": engine.layer_score_columns(_rule_columns(frame)),
            "isolation_forest": forest.score(matrix),
            "xgboost": booster.score(matrix),
        }

    tick = time.time()
    val_cases = cases_in_block(labels, *split.validation)
    test_cases = cases_in_block(labels, *split.test)
    val_days = split.validation[1] - split.validation[0] + 1
    test_days = split.test[1] - split.test[0] + 1
    val_frames = _block_frame(val, layer_scores(val), labels, val_cases)
    test_frames = _block_frame(test, layer_scores(test), labels, test_cases)
    timings["scoring_s"] = round(time.time() - tick, 1)

    report_layers: dict[str, Any] = {}
    for layer in LAYERS:
        val_daily, val_case_table = val_frames[layer]
        chosen = choose_threshold(val_daily, val_case_table, costs, k, val_days)
        threshold = chosen["threshold"]
        test_daily, test_case_table = test_frames[layer]
        report_layers[layer] = {
            "threshold_chosen_on_validation": chosen,
            "cost_sensitivity_validation": cost_curve(
                val_daily, val_case_table, evaluation["costs"]["sensitivity_ratios"],
                costs.c_fp, val_days, k,
            ),
            "validation": evaluate_block(
                val_daily, val_case_table, threshold, costs=costs, k=k, n_days=val_days
            ),
            "test": evaluate_block(
                test_daily, test_case_table, threshold, costs=costs, k=k, n_days=test_days
            ),
        }

    rule_firing = {
        rule_id: int((scores > 0).sum())
        for rule_id, scores in engine.score_columns(_rule_columns(test)).items()
    }
    if artifacts_dir is not None:
        target = Path(artifacts_dir)
        forest.save(target)
        booster.save(target)

    warnings: list[str] = []
    for name, cases in (("validation", val_cases), ("test", test_cases)):
        if cases["case_id"].nunique() == 0:
            warnings.append(
                f"The {name} block contains no case: operating-point and case-detection figures "
                "are not meaningful for this run (the `light` profile places cases at random)."
            )
    if val_cases["case_id"].nunique() == 0:
        warnings.append(
            "No validation case: the alert threshold cannot be chosen (+inf = no alert)."
        )

    timings["total_s"] = round(time.time() - started, 1)
    return {
        "run": {
            "profile": profile,
            "seed": seed,
            "model_seed": model_seed,
            "transactions_file": Path(transactions_path).name,
            "labels_file": Path(labels_path).name,
            "k_alerts_per_day": k,
            "costs": {"c_fp": costs.c_fp, "c_fn": costs.c_fn},
            "versions": {
                "python": platform.python_version(),
                "pandas": pd.__version__,
                "numpy": np.__version__,
                "scikit_learn": sklearn.__version__,
                "xgboost": xgboost.__version__,
            },
            "layer_versions": {
                "rules": engine.version,
                "isolation_forest": forest.version,
                "xgboost": booster.version,
            },
            "timings": timings,
            "test_block_evaluated": True,
        },
        "split": {name: list(split.range_of(name)) for name in ("warmup", "train", "validation", "test")},
        "data": data_summary,
        "features": list(MODEL_FEATURES),
        "imbalance": {
            "xgboost": booster.fit_info,
            "isolation_forest": "no label used; fitted on the whole training block",
        },
        "rules_fired_rows_test": rule_firing,
        "xgboost_feature_importance": booster.feature_importance(),
        "warnings": warnings,
        "layers": report_layers,
    }


def write_report(report: Mapping[str, Any], path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, sort_keys=True, default=float) + "\n", encoding="utf-8")
    return target
