import copy
import inspect

import numpy as np
import pandas as pd
import pytest
from synthetic_data import ORIGIN, make_transactions

from aml.models import pipeline
from aml.models.config import load_scoring_config
from aml.models.isolation_forest import IsolationForestLayer
from aml.models.metrics import CostParams, choose_threshold, top_k_metrics, wilson_interval
from aml.models.xgboost_layer import XGBoostLayer

CONFIG = load_scoring_config()


def toy_matrix(seed=0, rows=3000, positives=30):
    rng = np.random.default_rng(seed)
    X = rng.normal(size=(rows, 5))
    y = np.zeros(rows, dtype=int)
    y[:positives] = 1
    X[:positives, 0] += 3.0
    X[:positives, 1] += 2.0
    X[5, 2] = np.nan
    return X, y


def small_params(name):
    params = copy.deepcopy(CONFIG["models"][name])
    params["n_estimators"] = 40
    return params


# --- reproducibility --------------------------------------------------------------------------

def test_isolation_forest_is_reproducible_and_score_is_normalised():
    X, _ = toy_matrix()
    names = [f"f{i}" for i in range(5)]
    first = IsolationForestLayer(small_params("isolation_forest"), 7, names).fit(X)
    second = IsolationForestLayer(small_params("isolation_forest"), 7, names).fit(X)
    other = IsolationForestLayer(small_params("isolation_forest"), 8, names).fit(X)
    scores = first.score(X)
    assert np.array_equal(scores, second.score(X))
    assert not np.array_equal(scores, other.score(X))
    assert scores.min() >= 0.0 and scores.max() <= 1.0
    assert scores[:30].mean() > scores[30:].mean()  # planted anomalies score higher


def test_isolation_forest_fit_takes_no_label():
    assert list(inspect.signature(IsolationForestLayer.fit).parameters) == ["self", "matrix"]


def test_xgboost_is_reproducible_with_the_same_seed():
    X, y = toy_matrix()
    names = [f"f{i}" for i in range(5)]
    a = XGBoostLayer(small_params("xgboost"), 3, names).fit(X, y).score(X)
    b = XGBoostLayer(small_params("xgboost"), 3, names).fit(X, y).score(X)
    assert np.array_equal(a, b)


# --- class imbalance and early stopping ----------------------------------------------------------

def test_scale_pos_weight_auto_is_negatives_over_positives():
    X, y = toy_matrix()
    layer = XGBoostLayer(small_params("xgboost"), 0, [f"f{i}" for i in range(5)])
    layer.fit(X, y)
    assert layer.fit_info["scale_pos_weight"] == pytest.approx((len(y) - 30) / 30)
    assert layer.fit_info["train_positive_rows"] == 30
    fixed = copy.deepcopy(small_params("xgboost"))
    fixed["scale_pos_weight"] = 12.5
    assert XGBoostLayer(fixed, 0, ["a"]).resolve_scale_pos_weight(y) == 12.5


def test_early_stopping_uses_validation_only_when_it_has_positives():
    X, y = toy_matrix()
    Xv, yv = toy_matrix(seed=1)
    names = [f"f{i}" for i in range(5)]
    with_val = XGBoostLayer(small_params("xgboost"), 0, names).fit(X, y, validation=(Xv, yv))
    without = XGBoostLayer(small_params("xgboost"), 0, names).fit(
        X, y, validation=(Xv, np.zeros_like(yv)))
    assert with_val.fit_info["early_stopping_on_validation"] is True
    assert without.fit_info["early_stopping_on_validation"] is False


def test_models_survive_a_save_load_round_trip(tmp_path):
    X, y = toy_matrix()
    names = [f"f{i}" for i in range(5)]
    forest = IsolationForestLayer(small_params("isolation_forest"), 1, names).fit(X)
    booster = XGBoostLayer(small_params("xgboost"), 1, names).fit(X, y)
    forest.save(tmp_path)
    booster.save(tmp_path)
    assert np.allclose(IsolationForestLayer.load(tmp_path).score(X), forest.score(X))
    assert np.allclose(XGBoostLayer.load(tmp_path).score(X), booster.score(X))


# --- metrics and threshold selection ----------------------------------------------------------------

def daily(rows):
    return pd.DataFrame(rows, columns=["account_id", "day", "score", "positive"])


def test_precision_and_recall_at_k_on_a_hand_made_case():
    frame = daily([("a", 1, 0.9, True), ("b", 1, 0.8, False), ("c", 1, 0.1, False),
                   ("d", 2, 0.7, False), ("e", 2, 0.6, True)])
    one = top_k_metrics(frame, 1)
    assert one["precision_at_k"] == 0.5 and one["recall_at_k"] == 0.5
    assert one["precision_ceiling"] == 1.0
    two = top_k_metrics(frame, 2)
    assert two["precision_at_k"] == 0.5 and two["recall_at_k"] == 1.0
    assert two["precision_ceiling"] == 0.5 and two["precision_at_k_normalised"] == 1.0


def test_wilson_interval_matches_the_value_quoted_in_the_plan():
    low, high = wilson_interval(4, 5)
    assert (round(low, 2), round(high, 2)) == (0.38, 0.96)


def test_threshold_minimises_cost_under_the_alert_budget():
    frame = daily([("n1", 1, 0.95, False), ("p1", 1, 0.90, True), ("n2", 1, 0.5, False),
                   ("n3", 2, 0.45, False), ("n4", 2, 0.4, False), ("n5", 2, 0.1, False)])
    cases = pd.DataFrame({"case_id": ["c1"], "scenario": ["mule"], "sophistication": ["low"],
                          "start_day": [1], "end_day": [1], "accounts": [1], "best_score": [0.90]})
    costs = CostParams(1, 200)
    best = choose_threshold(frame, cases, costs, k_alerts_per_day=1.0, n_days=2)
    assert best["threshold"] == 0.90 and best["cases_detected"] == 1 and best["false_alerts"] == 1
    assert best["cost"] == 1
    # a tighter budget makes the detecting threshold infeasible: it falls back to no alert
    tight = choose_threshold(frame, cases, costs, k_alerts_per_day=0.4, n_days=2)
    assert tight["alerts"] == 0 and tight["cases_missed"] == 1
    # cheap misses: with r = 0.5 raising no alert at all is the cheapest choice
    cheap = choose_threshold(frame, cases, CostParams(1, 0.5), k_alerts_per_day=1.0, n_days=2)
    assert cheap["alerts"] == 0


# --- end to end on a small synthetic dataset ---------------------------------------------------------

def synthetic_run(tmp_path, monkeypatch):
    threshold = CONFIG["reporting_threshold"]
    suspects = {"acct-000003": (20, "train"), "acct-000004": (60, "validation"),
                "acct-000005": (78, "test")}
    extra = []
    for account, (start, _) in suspects.items():
        for day in range(start, start + 4):
            for hour in range(6):
                extra.append({
                    "timestamp": ORIGIN + pd.Timedelta(days=day - 1, hours=9 + hour),
                    "source_account_id": account, "target_account_id": "ext-cash",
                    "amount": round(0.95 * threshold, 2), "channel": "cash_deposit", "city": "Rabat"})
    transactions = make_transactions(seed=9, n_accounts=40, days=90, threshold=threshold, extra=extra)
    transactions_path = tmp_path / "transactions.csv"
    transactions.to_csv(transactions_path, index=False)
    rows = []
    for index, (account, (start, _)) in enumerate(suspects.items(), start=1):
        begin = ORIGIN + pd.Timedelta(days=start - 1)
        end = ORIGIN + pd.Timedelta(days=start + 2, hours=23)
        rows.append({"account_id": account, "tx_id": "", "scenario": "structuring",
                     "role": "depositor", "start_ts": begin.strftime("%Y-%m-%dT%H:%M:%SZ"),
                     "end_ts": end.strftime("%Y-%m-%dT%H:%M:%SZ"), "case_id": f"case-{index:03d}",
                     "sophistication": "low"})
    labels_path = tmp_path / "labels.csv"
    pd.DataFrame(rows).to_csv(labels_path, index=False)

    config = copy.deepcopy(CONFIG)
    config["models"]["isolation_forest"]["n_estimators"] = 20
    config["models"]["xgboost"]["n_estimators"] = 30

    calls: dict = {"if_rows": None, "xgb_rows": None, "threshold_days": []}
    original_if, original_xgb, original_choose = (
        IsolationForestLayer.fit, XGBoostLayer.fit, pipeline.choose_threshold)

    def record_if(self, matrix):
        calls["if_rows"] = len(matrix)
        return original_if(self, matrix)

    def record_xgb(self, matrix, labels, validation=None):
        calls["xgb_rows"] = len(matrix)
        return original_xgb(self, matrix, labels, validation)

    def record_choose(daily_frame, *args, **kwargs):
        calls["threshold_days"].append((int(daily_frame["day"].min()), int(daily_frame["day"].max())))
        return original_choose(daily_frame, *args, **kwargs)

    monkeypatch.setattr(IsolationForestLayer, "fit", record_if)
    monkeypatch.setattr(XGBoostLayer, "fit", record_xgb)
    monkeypatch.setattr(pipeline, "choose_threshold", record_choose)
    report = pipeline.run_baseline(
        transactions_path, labels_path, seed=1, profile="synthetic", scoring_config=config,
        artifacts_dir=tmp_path / "models", origin=ORIGIN)
    return report, calls


def test_pipeline_end_to_end_respects_the_temporal_protocol(tmp_path, monkeypatch):
    report, calls = synthetic_run(tmp_path, monkeypatch)
    blocks = report["data"]["blocks"]
    assert calls["if_rows"] == calls["xgb_rows"] == blocks["train"]["events"]
    # thresholds are chosen on validation days only (57-72), once per layer
    assert calls["threshold_days"] and all(span[0] >= 57 and span[1] <= 72 for span in calls["threshold_days"])
    assert set(report["layers"]) == {"rules", "isolation_forest", "xgboost"}
    assert report["warnings"] == [] and report["run"]["test_block_evaluated"] is True
    for layer in report["layers"].values():
        assert layer["test"]["operating_point"]["threshold"] == layer[
            "threshold_chosen_on_validation"]["threshold"]
    assert all(blocks[name]["positive_events"] > 0 for name in blocks)
    assert (tmp_path / "models" / "xgboost.json").exists()


def test_pipeline_is_deterministic_for_a_given_seed(tmp_path, monkeypatch):
    first, _ = synthetic_run(tmp_path, monkeypatch)
    second, _ = synthetic_run(tmp_path, monkeypatch)
    for report in (first, second):
        report["run"].pop("timings")
    assert first == second
