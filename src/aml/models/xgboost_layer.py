"""XGBoost layer (supervised), trained on the labelled training block only.

Class imbalance (well under 1 % positive rows) is handled with the positive-class weight
``scale_pos_weight`` (``auto`` = negatives / positives of the training block). The number of
trees is chosen by early stopping on the *validation* block (rule L-7); the training block never
sees validation or test rows. The raw probability is used as the layer score: weighting shifts its
calibration, which is harmless for ranking and for a threshold chosen on validation, but it must
not be read as a probability of laundering.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
from xgboost import XGBClassifier

LAYER_NAME = "xgboost"


class XGBoostLayer:
    def __init__(self, params: Mapping[str, Any], seed: int, feature_names: Sequence[str]):
        self.params = dict(params)
        self.seed = int(seed)
        self.feature_names = list(feature_names)
        self.version = str(params["version"])
        self.model: XGBClassifier | None = None
        self.fit_info: dict[str, Any] = {}

    def resolve_scale_pos_weight(self, labels: np.ndarray) -> float:
        positives = int(np.sum(labels))
        negatives = len(labels) - positives
        setting = self.params.get("scale_pos_weight", "auto")
        if setting == "auto":
            return float(negatives / positives) if positives else 1.0
        return float(setting)

    def fit(
        self,
        matrix: np.ndarray,
        labels: np.ndarray,
        validation: tuple[np.ndarray, np.ndarray] | None = None,
    ) -> XGBoostLayer:
        labels = np.asarray(labels, dtype=int)
        weight = self.resolve_scale_pos_weight(labels)
        use_validation = (
            validation is not None and int(np.sum(validation[1])) > 0 and int(np.sum(labels)) > 0
        )
        self.model = XGBClassifier(
            n_estimators=int(self.params["n_estimators"]),
            learning_rate=float(self.params["learning_rate"]),
            max_depth=int(self.params["max_depth"]),
            min_child_weight=float(self.params["min_child_weight"]),
            subsample=float(self.params["subsample"]),
            colsample_bytree=float(self.params["colsample_bytree"]),
            tree_method=str(self.params["tree_method"]),
            n_jobs=int(self.params["n_jobs"]),
            scale_pos_weight=weight,
            objective="binary:logistic",
            eval_metric="aucpr",
            early_stopping_rounds=int(self.params["early_stopping_rounds"]) if use_validation else None,
            random_state=self.seed,
        )
        eval_set = [(validation[0], np.asarray(validation[1], dtype=int))] if use_validation else None
        self.model.fit(np.asarray(matrix, dtype=np.float32), labels, eval_set=eval_set, verbose=False)
        self.fit_info = {
            "scale_pos_weight": weight,
            "train_rows": len(labels),
            "train_positive_rows": int(labels.sum()),
            "early_stopping_on_validation": bool(use_validation),
            "best_iteration": int(self.model.best_iteration) if use_validation else None,
            "n_trees": int(self.model.get_booster().num_boosted_rounds()),
        }
        return self

    def score(self, matrix: np.ndarray) -> np.ndarray:
        if self.model is None:
            raise RuntimeError("fit() must be called first")
        return self.model.predict_proba(np.asarray(matrix, dtype=np.float32))[:, 1]

    def feature_importance(self) -> dict[str, float]:
        if self.model is None:
            raise RuntimeError("fit() must be called first")
        values = self.model.feature_importances_
        ranked = sorted(zip(self.feature_names, values, strict=True), key=lambda item: -item[1])
        return {name: round(float(value), 6) for name, value in ranked}

    def save(self, directory: str | Path) -> None:
        if self.model is None:
            raise RuntimeError("fit() must be called first")
        target = Path(directory)
        target.mkdir(parents=True, exist_ok=True)
        self.model.save_model(target / "xgboost.json")
        (target / "xgboost_meta.json").write_text(
            json.dumps(
                {"version": self.version, "seed": self.seed, "features": self.feature_names,
                 "params": self.params, "fit_info": self.fit_info}, indent=2, sort_keys=True,
            ) + "\n",
            encoding="utf-8",
        )

    @classmethod
    def load(cls, directory: str | Path) -> XGBoostLayer:
        source = Path(directory)
        meta = json.loads((source / "xgboost_meta.json").read_text(encoding="utf-8"))
        layer = cls(meta["params"], meta["seed"], meta["features"])
        layer.model = XGBClassifier()
        layer.model.load_model(source / "xgboost.json")
        layer.fit_info = meta["fit_info"]
        return layer
