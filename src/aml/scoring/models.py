"""Temporal training, calibration and comparison for the three phase-4 baselines."""

from __future__ import annotations

import gc
import hashlib
import json
import math
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from aml.scoring.dataset import FEATURE_NAMES, build_account_days, temporal_masks


def load_config(path: str | Path = "config/scoring.yaml") -> dict[str, Any]:
    config = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    config["artifact_dir"] = os.environ.get("AML_MODEL_ARTIFACT_DIR", config["artifact_dir"])
    streaming = config["streaming"]
    streaming["input_topic"] = os.environ.get(
        "AML_SCORING_INPUT_TOPIC", streaming["input_topic"]
    )
    streaming["scores_topic"] = os.environ.get(
        "AML_SCORING_SCORES_TOPIC", streaming["scores_topic"]
    )
    streaming["alerts_topic"] = os.environ.get(
        "AML_SCORING_ALERTS_TOPIC", streaming["alerts_topic"]
    )
    streaming["operating_model"] = os.environ.get(
        "AML_SCORING_MODEL", streaming["operating_model"]
    )
    streaming["model_seed"] = int(
        os.environ.get("AML_SCORING_MODEL_SEED", streaming["model_seed"])
    )
    streaming["bootstrap_servers"] = os.environ.get(
        "AML_SCORING_BOOTSTRAP_SERVERS", streaming["bootstrap_servers"]
    )
    if config["evaluation"]["k_alerts_per_day"] < 1:
        raise ValueError("k_alerts_per_day must be positive")
    if not config["seeds"]:
        raise ValueError("at least one evaluation seed is required")
    return config


def rule_prediction(
    features: dict[str, Any], rules_config: dict[str, Any] | None = None
) -> tuple[float, list[str]]:
    """Four explainable baseline rules with scores in [0, 1]."""
    rules_config = rules_config or {}
    def value(name: str) -> float:
        raw = features.get(name)
        return 0.0 if raw is None else float(raw)

    hits: list[tuple[str, float]] = []
    structuring = rules_config.get("structuring", {})
    if (
        value("tx_count_7d") >= float(structuring.get("min_tx_count_7d", 3))
        and value("near_threshold_share_7d")
        >= float(structuring.get("min_near_threshold_share", 0.30))
        and value("cash_share_7d") >= float(structuring.get("min_cash_share", 0.40))
    ):
        hits.append(("structuring", float(structuring.get("score", 0.95))))
    delay = features.get("avg_in_to_out_delay_s_24h")
    rapid = rules_config.get("rapid_in_out", {})
    if (
        value("tx_count_1h") >= float(rapid.get("min_tx_count_1h", 2))
        and delay is not None
        and 0 <= float(delay) <= float(rapid.get("max_delay_seconds", 6 * 3600))
        and value("inflow_outflow_ratio_24h")
        >= float(rapid.get("min_inflow_outflow_ratio", 0.70))
    ):
        hits.append(("rapid_in_out", float(rapid.get("score", 0.90))))
    days_since = features.get("days_since_previous_tx")
    dormant = rules_config.get("dormant_then_active", {})
    if (
        days_since is not None
        and float(days_since) >= float(dormant.get("min_days_dormant", 14))
        and (
            value("amount_to_avg_ratio") >= float(dormant.get("min_amount_ratio", 3.0))
            or value("total_amount_24h_mad")
            >= float(dormant.get("min_total_amount_24h_mad", 100_000))
        )
    ):
        hits.append(("dormant_then_active", float(dormant.get("score", 0.80))))
    channel = rules_config.get("high_risk_channel", {})
    if (
        value("current_channel_international") >= 1
        or (
            value("current_channel_cash") >= 1
            and value("total_amount_24h_mad")
            >= float(channel.get("min_amount_24h_mad", 10_000))
        )
    ):
        hits.append(("high_risk_channel", float(channel.get("score", 0.65))))
    return max((score for _, score in hits), default=0.0), [name for name, _ in hits]


def _require_ml() -> tuple[Any, Any, Any, Any]:
    try:
        import joblib
        import numpy as np
        from sklearn.ensemble import IsolationForest
        from xgboost import XGBClassifier
    except ImportError as exc:
        raise RuntimeError("Installez les modèles avec `python -m pip install -e '.[ml]'`.") from exc
    return joblib, np, IsolationForest, XGBClassifier


def _matrix(rows: list[dict[str, Any]], medians: list[float] | None = None) -> tuple[Any, list[float]]:
    _, np, _, _ = _require_ml()
    columns: list[list[float]] = [[] for _ in FEATURE_NAMES]
    for row in rows:
        for index, name in enumerate(FEATURE_NAMES):
            value = row["features"].get(name)
            columns[index].append(float(value) if value is not None else math.nan)
    matrix = np.asarray(columns, dtype=float).T
    if medians is None:
        medians = []
        for index in range(matrix.shape[1]):
            finite = matrix[:, index][np.isfinite(matrix[:, index])]
            medians.append(float(np.median(finite)) if finite.size else 0.0)
    for index, median in enumerate(medians):
        matrix[~np.isfinite(matrix[:, index]), index] = median
    return matrix, medians


def rule_scores(
    rows: list[dict[str, Any]], rules_config: dict[str, Any] | None = None
) -> tuple[list[float], list[list[str]]]:
    pairs = [rule_prediction(row["features"], rules_config) for row in rows]
    return [pair[0] for pair in pairs], [pair[1] for pair in pairs]


def _fit_bundle(rows: list[dict[str, Any]], train_ids: list[int], validation_ids: list[int],
                config: dict[str, Any], seed: int, *, artifact_path: Path) -> dict[str, Any]:
    joblib, np, IsolationForest, XGBClassifier = _require_ml()
    train = [rows[index] for index in train_ids]
    validation = [rows[index] for index in validation_ids]
    y_train = np.asarray([row["label"] for row in train], dtype=int)
    if len(set(y_train.tolist())) < 2:
        raise ValueError(f"Seed {seed}: bloc d'entraînement sans deux classes")
    x_train, medians = _matrix(train)
    x_validation, _ = _matrix(validation, medians)

    limits = config["evaluation"]
    max_iforest_rows = int(limits["max_iforest_rows"])
    if len(x_train) > max_iforest_rows:
        sample = np.random.default_rng(seed).choice(
            len(x_train), max_iforest_rows, replace=False
        )
        if_train = x_train[sample]
    else:
        if_train = x_train
    center = np.median(if_train, axis=0)
    scale = np.median(np.abs(if_train - center), axis=0)
    scale[scale == 0] = 1.0
    iforest = IsolationForest(
        n_estimators=160,
        max_samples=min(512, len(if_train)),
        contamination="auto",
        random_state=seed,
        n_jobs=2,
    ).fit((if_train - center) / scale)
    if_train_raw = -iforest.decision_function((if_train - center) / scale)
    if_low, if_high = (float(value) for value in np.quantile(if_train_raw, [0.01, 0.99]))
    if if_high <= if_low:
        if_high = if_low + 1e-9
    if_validation_raw = -iforest.decision_function((x_validation - center) / scale)
    if_validation_scores = np.clip((if_validation_raw - if_low) / (if_high - if_low), 0, 1)

    xgb_options = limits["xgboost"]
    positives = int(y_train.sum())
    negatives = len(y_train) - positives
    xgb = XGBClassifier(
        n_estimators=int(xgb_options["n_estimators"]),
        max_depth=int(xgb_options["max_depth"]),
        learning_rate=float(xgb_options["learning_rate"]),
        subsample=float(xgb_options["subsample"]),
        colsample_bytree=float(xgb_options["colsample_bytree"]),
        reg_lambda=float(xgb_options["reg_lambda"]),
        scale_pos_weight=max(1.0, negatives / max(1, positives)),
        objective="binary:logistic",
        eval_metric="logloss",
        tree_method="hist",
        n_jobs=2,
        random_state=seed,
    )
    xgb.fit(x_train, y_train)
    xgb_validation_scores = xgb.predict_proba(x_validation)[:, 1].astype(float)
    validation_rule_scores, _ = rule_scores(validation, config["rules"])

    thresholds: dict[str, float] = {}
    thresholds_by_ratio: dict[str, dict[str, float]] = {}
    validation_calibration: dict[str, dict[str, float]] = {}
    for name, scores in (
        ("rules", validation_rule_scores),
        ("isolation_forest", if_validation_scores.tolist()),
        ("xgboost", xgb_validation_scores.tolist()),
    ):
        threshold, summary = choose_threshold(validation, scores, limits)
        thresholds[name] = threshold
        validation_calibration[name] = summary
        thresholds_by_ratio[name] = {}
        for ratio in limits["sensitivity_ratios"]:
            ratio_limits = {**limits, "c_fn": int(ratio)}
            ratio_threshold, ratio_summary = choose_threshold(validation, scores, ratio_limits)
            thresholds_by_ratio[name][str(ratio)] = ratio_threshold
            validation_calibration[name][f"cost_ratio_{ratio}"] = ratio_summary["cost"]

    bundle = {
        "seed": seed,
        "feature_names": FEATURE_NAMES,
        "medians": medians,
        "iforest_center": center.tolist(),
        "iforest_scale": scale.tolist(),
        "iforest_low": if_low,
        "iforest_high": if_high,
        "iforest": iforest,
        "xgboost": xgb,
        "thresholds": thresholds,
        "thresholds_by_ratio": thresholds_by_ratio,
        "validation": validation_calibration,
        "version": "phase4-baselines-v1",
        "rules": config["rules"],
    }
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, artifact_path)
    return bundle


def _case_stats(rows: list[dict[str, Any]], alerted: list[bool]) -> dict[str, Any]:
    cases: dict[str, dict[str, str]] = {}
    detected: set[str] = set()
    first_alert_at: dict[str, datetime] = {}
    starts: dict[str, datetime] = {}
    for row, is_alerted in zip(rows, alerted, strict=True):
        for case_id in row["active_cases"]:
            cases.setdefault(
                case_id,
                {
                    "scenario": row["active_case_scenarios"][case_id],
                    "sophistication": row["active_case_levels"][case_id],
                },
            )
            starts.setdefault(
                case_id,
                datetime.fromisoformat(row["active_case_starts"][case_id]),
            )
            if is_alerted:
                detected.add(case_id)
                as_of = datetime.fromisoformat(row["as_of"])
                if case_id not in first_alert_at or as_of < first_alert_at[case_id]:
                    first_alert_at[case_id] = as_of
    by_scenario: dict[str, list[str]] = {}
    by_level: dict[str, list[str]] = {}
    for case_id, meta in cases.items():
        by_scenario.setdefault(meta["scenario"], []).append(case_id)
        by_level.setdefault(meta["sophistication"], []).append(case_id)
    delays = [
        (first_alert_at[case_id] - starts[case_id]).total_seconds() / 3600
        for case_id in detected
        if case_id in first_alert_at and first_alert_at[case_id] >= starts[case_id]
    ]
    return {
        "detected": len(detected),
        "total": len(cases),
        "rate": len(detected) / len(cases) if cases else None,
        "mean_detection_delay_hours": sum(delays) / len(delays) if delays else None,
        "detection_delays_hours": delays,
        "by_scenario": {
            key: {"detected": len(set(ids) & detected), "total": len(ids)}
            for key, ids in sorted(by_scenario.items())
        },
        "by_sophistication": {
            key: {"detected": len(set(ids) & detected), "total": len(ids)}
            for key, ids in sorted(by_level.items())
        },
    }


def top_k_mask(rows: list[dict[str, Any]], scores: list[float], k: int) -> list[bool]:
    by_day: dict[int, list[int]] = {}
    for index, row in enumerate(rows):
        by_day.setdefault(int(row["day"]), []).append(index)
    alerted = [False] * len(rows)
    for indexes in by_day.values():
        winners = sorted(indexes, key=lambda index: (-scores[index], rows[index]["account_id"]))[:k]
        for index in winners:
            alerted[index] = True
    return alerted


def _threshold_mask(scores: list[float], threshold: float) -> list[bool]:
    return [score >= threshold for score in scores]


def _cost_summary(rows: list[dict[str, Any]], alerted: list[bool], limits: dict[str, Any]) -> dict[str, Any]:
    _, np, _, _ = _require_ml()
    flags = np.asarray(alerted, dtype=bool)
    labels = np.asarray([row["label"] for row in rows], dtype=bool)
    fp = int(np.count_nonzero(flags & ~labels))
    cases = _case_stats(rows, alerted)
    false_negatives = cases["total"] - cases["detected"]
    return {
        "false_positive_account_days": fp,
        "missed_cases": false_negatives,
        "cost": int(limits["c_fp"]) * fp + int(limits["c_fn"]) * false_negatives,
        "alerted_account_days": sum(alerted),
    }


def choose_threshold(
    rows: list[dict[str, Any]], scores: list[float], limits: dict[str, Any]
) -> tuple[float, dict[str, float]]:
    """Choose a global threshold on validation by cost under average daily review capacity."""
    _, np, _, _ = _require_ml()
    if not rows:
        raise ValueError("validation block is empty")
    candidates = sorted(
        {float(value) for value in np.quantile(scores, np.linspace(0, 1, 201))}
        | {float(max(scores) + 1e-12)}
    )
    n_days = len({row["day"] for row in rows})
    capacity = int(limits["k_alerts_per_day"]) * n_days
    labels = np.asarray([row["label"] for row in rows], dtype=bool)
    values = np.asarray(scores, dtype=float)
    case_rows: dict[str, list[int]] = {}
    for index, row in enumerate(rows):
        for case_id in row["active_cases"]:
            case_rows.setdefault(case_id, []).append(index)
    feasible: list[tuple[int, float, int]] = []
    for threshold in candidates:
        flags = values >= threshold
        alerted_count = int(flags.sum())
        if alerted_count > capacity:
            continue
        false_positives = int(np.count_nonzero(flags & ~labels))
        detected_cases = sum(bool(flags[indexes].any()) for indexes in case_rows.values())
        missed_cases = len(case_rows) - detected_cases
        cost = (
            int(limits["c_fp"]) * false_positives
            + int(limits["c_fn"]) * missed_cases
        )
        feasible.append((cost, threshold, alerted_count))
    cost, threshold, alerted_count = min(feasible, key=lambda item: (item[0], -item[1]))
    return threshold, {
        "threshold": threshold,
        "cost": float(cost),
        "mean_alerts_per_day": alerted_count / n_days,
    }


def _score_bundle(rows: list[dict[str, Any]], bundle: dict[str, Any]) -> dict[str, list[float]]:
    _, np, _, _ = _require_ml()
    matrix, _ = _matrix(rows, bundle["medians"])
    transformed = (matrix - np.asarray(bundle["iforest_center"])) / np.asarray(
        bundle["iforest_scale"]
    )
    raw = -bundle["iforest"].decision_function(transformed)
    if_scores = np.clip(
        (raw - bundle["iforest_low"]) / (bundle["iforest_high"] - bundle["iforest_low"]),
        0,
        1,
    )
    xgb_scores = bundle["xgboost"].predict_proba(matrix)[:, 1]
    rules, _ = rule_scores(rows, bundle.get("rules"))
    return {
        "rules": [float(value) for value in rules],
        "isolation_forest": [float(value) for value in if_scores],
        "xgboost": [float(value) for value in xgb_scores],
    }


def score_one_feature_message(
    features: dict[str, Any], bundle: dict[str, Any], model_name: str
) -> tuple[float, list[str], list[dict[str, Any]]]:
    """Score a single C-06 feature payload for the Kafka consumer."""
    if model_name not in {"rules", "isolation_forest", "xgboost"}:
        raise ValueError(f"unknown scoring model: {model_name}")
    fired: list[str] = []
    row = {"features": features, "label": 0, "active_cases": [], "day": 0,
           "account_id": ""}
    if model_name == "rules":
        score, fired = rule_prediction(features, bundle.get("rules"))
        top = [{"feature": name, "value": None, "importance": None} for name in fired]
    else:
        _, np, _, _ = _require_ml()
        matrix, _ = _matrix([row], bundle["medians"])
    if model_name == "xgboost":
        estimator = bundle["xgboost"]
        importances = estimator.feature_importances_
        indexes = np.argsort(importances)[::-1]
        score = float(estimator.predict_proba(matrix)[0, 1])
        top = [
            {"feature": FEATURE_NAMES[int(index)], "value": features.get(FEATURE_NAMES[int(index)]),
             "importance": float(importances[int(index)])}
            for index in indexes[:3]
            if float(importances[int(index)]) > 0
        ]
    elif model_name == "isolation_forest":
        transformed = (matrix - np.asarray(bundle["iforest_center"])) / np.asarray(
            bundle["iforest_scale"]
        )
        raw = -float(bundle["iforest"].decision_function(transformed)[0])
        score = float(
            np.clip(
                (raw - bundle["iforest_low"])
                / (bundle["iforest_high"] - bundle["iforest_low"]),
                0,
                1,
            )
        )
        top = []
        _, fired = rule_prediction(features, bundle.get("rules"))
    return float(score), fired, top


def _classification_metrics(rows: list[dict[str, Any]], scores: list[float],
                            threshold: float, limits: dict[str, Any]) -> dict[str, Any]:
    _, np, _, _ = _require_ml()
    from sklearn.metrics import average_precision_score, roc_auc_score

    y = np.asarray([row["label"] for row in rows], dtype=int)
    score_array = np.asarray(scores, dtype=float)
    top_k = top_k_mask(rows, scores, int(limits["k_alerts_per_day"]))
    threshold_flags = _threshold_mask(scores, threshold)
    tp = sum(bool(flag and row["label"]) for row, flag in zip(rows, top_k, strict=True))
    n_alerts = sum(top_k)
    positives = int(y.sum())
    cases = _case_stats(rows, top_k)
    threshold_cost = _cost_summary(rows, threshold_flags, limits)
    days: dict[int, list[int]] = {}
    for index, row in enumerate(rows):
        days.setdefault(int(row["day"]), []).append(index)
    possible_tp = sum(
        min(int(y[indexes].sum()), int(limits["k_alerts_per_day"]), len(indexes))
        for indexes in (np.asarray(group, dtype=int) for group in days.values())
    )
    k_sensitivity = {}
    for k in limits["sensitivity_ks"]:
        flags = top_k_mask(rows, scores, int(k))
        k_tp = sum(bool(flag and row["label"]) for row, flag in zip(rows, flags, strict=True))
        k_alerts = sum(flags)
        k_positives = sum(row["label"] for row in rows)
        k_cases = _case_stats(rows, flags)
        k_sensitivity[str(k)] = {
            "precision": k_tp / k_alerts if k_alerts else 0.0,
            "recall": k_tp / k_positives if k_positives else None,
            "cases_detected": k_cases["detected"],
            "cases_total": k_cases["total"],
        }
    return {
        "pr_auc_average_precision": float(average_precision_score(y, score_array)),
        "roc_auc": float(roc_auc_score(y, score_array)) if len(set(y.tolist())) == 2 else None,
        "precision_at_k": tp / n_alerts if n_alerts else 0.0,
        "recall_at_k": tp / positives if positives else None,
        "normalized_precision_at_k": tp / possible_tp if possible_tp else None,
        "positive_account_days": positives,
        "account_days": len(rows),
        "test_threshold": threshold,
        "threshold_metrics": {
            **threshold_cost,
            "mean_alerts_per_day": threshold_cost["alerted_account_days"] / max(1, len(days)),
        },
        "top_k_cases": cases,
        "k_sensitivity": k_sensitivity,
        "curve": _sample_curves(y, score_array),
    }


def _sample_curves(y: Any, scores: Any) -> dict[str, list[float]]:
    _, np, _, _ = _require_ml()
    from sklearn.metrics import precision_recall_curve, roc_curve

    precision, recall, _ = precision_recall_curve(y, scores)
    fpr, tpr, _ = roc_curve(y, scores)

    def sample(x: Any, y_values: Any) -> dict[str, list[float]]:
        if len(x) <= 101:
            indexes = np.arange(len(x))
        else:
            indexes = np.unique(np.linspace(0, len(x) - 1, 101).astype(int))
        return {"x": [float(x[index]) for index in indexes],
                "y": [float(y_values[index]) for index in indexes]}

    pr = sample(recall, precision)
    roc = sample(fpr, tpr)
    return {"precision_recall": pr, "roc": roc}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def train_all(config: dict[str, Any]) -> dict[str, Any]:
    """Train one chronologically split bundle per seed and calibrate on validation only."""
    _, _, _, _ = _require_ml()
    import numpy as np
    import sklearn
    import xgboost

    artifact_dir = Path(config["artifact_dir"])
    summaries = []
    for seed in config["seeds"]:
        seed_started = time.perf_counter()
        transactions = Path(config["transactions_pattern"].format(
            profile=config["dataset_profile"], seed=seed
        ))
        labels = Path(config["labels_pattern"].format(
            profile=config["dataset_profile"], seed=seed
        ))
        if not transactions.exists() or not labels.exists():
            raise FileNotFoundError(
                f"Dataset manquant pour seed={seed}: générer {transactions} et {labels}"
            )
        feature_started = time.perf_counter()
        rows = build_account_days(transactions, labels, **config["features"])
        feature_seconds = time.perf_counter() - feature_started
        splits = temporal_masks(rows, config["evaluation"])
        bundle_path = artifact_dir / f"aml_seed_{seed}.joblib"
        training_started = time.perf_counter()
        bundle = _fit_bundle(
            rows, splits["train"], splits["validation"], config, int(seed),
            artifact_path=bundle_path,
        )
        training_seconds = time.perf_counter() - training_started
        summaries.append(
            {
                "seed": seed,
                "rows": {name: len(indices) for name, indices in splits.items()},
                "positive_train_days": sum(rows[index]["label"] for index in splits["train"]),
                "validation_calibration": bundle["validation"],
                "dataset_sha256": {
                    "transactions": _sha256(transactions),
                    "labels": _sha256(labels),
                },
                "artifact": str(bundle_path),
                "feature_build_seconds": round(feature_seconds, 3),
                "model_fit_and_calibration_seconds": round(training_seconds, 3),
                "total_seed_seconds": round(time.perf_counter() - seed_started, 3),
            }
        )
        del rows, splits, bundle
        gc.collect()
    manifest = {
        "profile": config["dataset_profile"],
        "seeds": list(config["seeds"]),
        "runtime_versions": {
            "numpy": np.__version__,
            "scikit_learn": sklearn.__version__,
            "xgboost": xgboost.__version__,
        },
        "role": "synthetic main dataset; labels used for training/evaluation only",
        "training": summaries,
    }
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "training_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return manifest


def _aggregate_metric(details: list[dict[str, Any]], name: str) -> dict[str, float | None]:
    _, np, _, _ = _require_ml()
    values = [item[name] for item in details if item[name] is not None]
    if not values:
        return {"mean": None, "std": None, "min": None, "max": None}
    array = np.asarray(values, dtype=float)
    return {
        "mean": float(array.mean()),
        "std": float(array.std(ddof=0)),
        "min": float(array.min()),
        "max": float(array.max()),
    }


def _aggregate_case_groups(
    details: list[dict[str, Any]], field: str
) -> dict[str, dict[str, Any]]:
    grouped: dict[str, dict[str, int]] = {}
    for item in details:
        for group, counts in item["top_k_cases"][field].items():
            current = grouped.setdefault(group, {"detected": 0, "total": 0})
            current["detected"] += int(counts["detected"])
            current["total"] += int(counts["total"])
    return {
        group: {
            **counts,
            "rate": counts["detected"] / counts["total"] if counts["total"] else None,
        }
        for group, counts in sorted(grouped.items())
    }


def evaluate_all(config: dict[str, Any]) -> dict[str, Any]:
    """Evaluate frozen per-seed models once on the test block; emit JSON and Markdown."""
    joblib, _, _, _ = _require_ml()
    details_by_model: dict[str, list[dict[str, Any]]] = {
        "rules": [], "isolation_forest": [], "xgboost": []
    }
    per_seed: list[dict[str, Any]] = []
    for seed in config["seeds"]:
        seed_started = time.perf_counter()
        transactions = Path(config["transactions_pattern"].format(
            profile=config["dataset_profile"], seed=seed
        ))
        labels = Path(config["labels_pattern"].format(
            profile=config["dataset_profile"], seed=seed
        ))
        rows = build_account_days(transactions, labels, **config["features"])
        test_ids = temporal_masks(rows, config["evaluation"])["test"]
        test_rows = [rows[index] for index in test_ids]
        bundle_path = Path(config["artifact_dir"]) / f"aml_seed_{seed}.joblib"
        if not bundle_path.exists():
            raise FileNotFoundError(f"Modèle manquant {bundle_path}; exécuter `manage.py train` d'abord")
        bundle = joblib.load(bundle_path)
        scores_by_model = _score_bundle(test_rows, bundle)
        seed_result: dict[str, Any] = {"seed": seed, "test_rows": len(test_rows), "models": {}}
        for name, scores in scores_by_model.items():
            model_result = _classification_metrics(
                test_rows, scores, float(bundle["thresholds"][name]), config["evaluation"]
            )
            details_by_model[name].append(model_result)
            model_result["cost_sensitivity"] = {}
            for ratio in config["evaluation"]["sensitivity_ratios"]:
                threshold = float(bundle["thresholds_by_ratio"][name][str(ratio)])
                ratio_limits = {**config["evaluation"], "c_fn": int(ratio)}
                cost = _cost_summary(
                    test_rows, _threshold_mask(scores, threshold), ratio_limits
                )
                model_result["cost_sensitivity"][str(ratio)] = {
                    "threshold": threshold,
                    **cost,
                }
            seed_result["models"][name] = model_result
        seed_result["evaluation_seconds"] = round(time.perf_counter() - seed_started, 3)
        per_seed.append(seed_result)
        del rows, test_rows, bundle, scores_by_model
        gc.collect()

    aggregate: dict[str, Any] = {}
    metric_names = (
        "pr_auc_average_precision", "roc_auc", "precision_at_k", "recall_at_k",
        "normalized_precision_at_k",
    )
    for model_name, details in details_by_model.items():
        aggregate[model_name] = {
            metric: _aggregate_metric(details, metric) for metric in metric_names
        }
        aggregate[model_name]["cases_detected"] = sum(
            item["top_k_cases"]["detected"] for item in details
        )
        aggregate[model_name]["cases_total"] = sum(
            item["top_k_cases"]["total"] for item in details
        )
        aggregate[model_name]["case_detection_rate"] = (
            aggregate[model_name]["cases_detected"] / aggregate[model_name]["cases_total"]
            if aggregate[model_name]["cases_total"] else None
        )
        aggregate[model_name]["threshold_cost_by_seed"] = [
            item["threshold_metrics"]["cost"] for item in details
        ]
        aggregate[model_name]["cost_sensitivity"] = {
            str(ratio): {
                "mean_cost": sum(
                    item["cost_sensitivity"][str(ratio)]["cost"] for item in details
                ) / len(details),
                "cost_by_seed": [
                    item["cost_sensitivity"][str(ratio)]["cost"] for item in details
                ],
            }
            for ratio in config["evaluation"]["sensitivity_ratios"]
        }
        aggregate[model_name]["k_sensitivity"] = {
            str(k): {
                "mean_precision": _aggregate_metric(
                    [{"p": item["k_sensitivity"][str(k)]["precision"]} for item in details], "p"
                )["mean"],
                "mean_recall": _aggregate_metric(
                    [{"r": item["k_sensitivity"][str(k)]["recall"]} for item in details], "r"
                )["mean"],
                "cases_detected": sum(
                    item["k_sensitivity"][str(k)]["cases_detected"] for item in details
                ),
                "cases_total": sum(
                    item["k_sensitivity"][str(k)]["cases_total"] for item in details
                ),
            }
            for k in config["evaluation"]["sensitivity_ks"]
        }
        aggregate[model_name]["typology_detection"] = _aggregate_case_groups(
            details, "by_scenario"
        )
        aggregate[model_name]["sophistication_detection"] = _aggregate_case_groups(
            details, "by_sophistication"
        )
        all_delays = [
            delay
            for item in details
            for delay in item["top_k_cases"]["detection_delays_hours"]
        ]
        aggregate[model_name]["mean_detection_delay_hours"] = (
            sum(all_delays) / len(all_delays) if all_delays else None
        )
    report = {
        "title": "Comparaison des modèles de base AML — données simulées",
        "dataset": {
            "profile": config["dataset_profile"],
            "role": "jeu synthétique principal généré localement; aucun usage comme preuve bancaire réelle",
            "seeds": list(config["seeds"]),
            "limitations": [
                "Transactions et labels sont simulés par le même projet; les modèles peuvent apprendre les règles du générateur.",
                "Les résultats n'estiment pas la performance sur les transactions réelles d'une banque marocaine.",
                "La qualité par scénario reste incertaine avec peu de cas par graine.",
                "Les seuils de règles, le coût FN/FP et k=50 sont des hypothèses de l'équipe.",
            ],
        },
        "evaluation": config["evaluation"],
        "training": json.loads(
            (Path(config["artifact_dir"]) / "training_manifest.json").read_text(encoding="utf-8")
        )["training"],
        "aggregate_test": aggregate,
        "per_seed": per_seed,
        "out_of_scope": ["graphe", "SHAP", "dashboard complet", "test adversarial/dérive"],
    }
    report["training_manifest_sha256"] = _sha256(
        Path(config["artifact_dir"]) / "training_manifest.json"
    )
    json_path = Path(config["report_json"])
    markdown_path = Path(config["report_markdown"])
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    return report


def render_markdown(report: dict[str, Any]) -> str:
    metrics = report["aggregate_test"]
    names = {"rules": "Règles", "isolation_forest": "Isolation Forest", "xgboost": "XGBoost"}
    lines = [
        "# Comparaison des modèles de base AML",
        "",
        (f"Jeu : **{report['dataset']['profile']} synthétique**, graines "
         f"{', '.join(map(str, report['dataset']['seeds']))}. Labels réservés à "
         "l'entraînement/évaluation; jamais consommés par le scorer."),
        "",
        "| Modèle | PR-AUC (moy. ± écart-type) | ROC-AUC | Précision@k | Rappel@k | Rappel cas (top-k) | Coût au seuil validé |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name, title in names.items():
        metric = metrics[name]
        def fmt(key: str, metric: dict[str, Any] = metric) -> str:
            value = metric[key]
            if value["mean"] is None:
                return "n.d."
            return f"{value['mean']:.4f} ± {value['std']:.4f}"
        cost = ", ".join(map(str, metric["threshold_cost_by_seed"]))
        lines.append(
            f"| {title} | {fmt('pr_auc_average_precision')} | {fmt('roc_auc')} | "
            f"{fmt('precision_at_k')} | {fmt('recall_at_k')} | "
            f"{metric['cases_detected']}/{metric['cases_total']} ({metric['case_detection_rate']:.1%}) | {cost} |"
        )
    lines.extend(["", "## Limites et périmètre", ""])
    lines.extend(f"- {item}" for item in report["dataset"]["limitations"])
    lines.extend(["", "## Détection des cas par typologie", ""])
    lines.extend([
        "| Modèle | Typologie | Cas détectés / total | Rappel |",
        "|---|---|---:|---:|",
    ])
    for model_name, title in names.items():
        for scenario, counts in metrics[model_name]["typology_detection"].items():
            rate = "n.d." if counts["rate"] is None else f"{counts['rate']:.1%}"
            lines.append(
                f"| {title} | {scenario} | {counts['detected']}/{counts['total']} | {rate} |"
            )
    lines.extend(["", "## Sensibilité au coût des cas manqués", ""])
    lines.extend([
        "| Modèle | r=10 | r=50 | r=100 | r=200 | r=500 | r=1000 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ])
    for model_name, title in names.items():
        values = [
            f"{metrics[model_name]['cost_sensitivity'][str(ratio)]['mean_cost']:.0f}"
            for ratio in report["evaluation"]["sensitivity_ratios"]
        ]
        lines.append(f"| {title} | " + " | ".join(values) + " |")
    lines.extend([
        "- Le seuil est choisi sur la validation uniquement; les résultats du test sont agrégés par graine.",
        "- Le rappel de cas affiché est calculé à partir des alertes top-k par jour.",
        "- PR-AUC est l'average precision calculée sur le bloc de test; les courbes PR/ROC échantillonnées sont dans le JSON.",
        "- Le graphe, SHAP et le dashboard complet appartiennent à la phase 5.",
        "",
    ])
    return "\n".join(lines)
