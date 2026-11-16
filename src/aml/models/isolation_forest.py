"""Isolation Forest layer (unsupervised), trained on a period assumed mostly normal.

The forest never sees a label: it is fitted on the training block as it is. The raw anomaly
score (larger = more anomalous) is mapped to [0, 1] with the empirical distribution of the
training scores, so that ``score = 0.9`` reads "more anomalous than 90 % of the training rows".
This mapping is monotonic and uses training data only.

Null features (not applicable, e.g. no outflow in 24 h) are replaced by -1, a value no feature
can take, identically at training and scoring time.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from sklearn.ensemble import IsolationForest

LAYER_NAME = "isolation_forest"
MISSING_FILL = -1.0


def _prepare(matrix: np.ndarray) -> np.ndarray:
    return np.nan_to_num(np.asarray(matrix, dtype=np.float32), nan=MISSING_FILL)


class IsolationForestLayer:
    def __init__(self, params: Mapping[str, Any], seed: int, feature_names: Sequence[str]):
        self.params = dict(params)
        self.seed = int(seed)
        self.feature_names = list(feature_names)
        self.version = str(params["version"])
        self.model: IsolationForest | None = None
        self.calibration: np.ndarray | None = None

    def fit(self, matrix: np.ndarray) -> IsolationForestLayer:
        data = _prepare(matrix)
        self.model = IsolationForest(
            n_estimators=int(self.params["n_estimators"]),
            max_samples=self.params["max_samples"],
            contamination=self.params.get("contamination", "auto"),
            random_state=self.seed,
            n_jobs=1,
        )
        self.model.fit(data)
        # Calibration grid on a seeded subsample of the training rows (training data only).
        rng = np.random.default_rng(self.seed)
        sample_size = min(len(data), int(self.params.get("calibration_sample_rows", len(data))))
        sample = data[rng.choice(len(data), size=sample_size, replace=False)]
        raw = -self.model.score_samples(sample)
        grid = int(self.params["score_quantile_grid"])
        self.calibration = np.quantile(raw, np.linspace(0.0, 1.0, grid))
        return self

    def raw_score(self, matrix: np.ndarray) -> np.ndarray:
        if self.model is None:
            raise RuntimeError("fit() must be called first")
        return -self.model.score_samples(_prepare(matrix))

    def score(self, matrix: np.ndarray) -> np.ndarray:
        """Normalised anomaly score in [0, 1]."""
        if self.calibration is None:
            raise RuntimeError("fit() must be called first")
        grid = self.calibration
        # np.interp needs increasing x; ties in the grid are harmless.
        return np.interp(self.raw_score(matrix), grid, np.linspace(0.0, 1.0, len(grid)))

    def save(self, directory: str | Path) -> None:
        target = Path(directory)
        target.mkdir(parents=True, exist_ok=True)
        joblib.dump({"model": self.model, "calibration": self.calibration}, target / "isolation_forest.joblib")
        (target / "isolation_forest.json").write_text(
            json.dumps(
                {"version": self.version, "seed": self.seed, "features": self.feature_names,
                 "params": self.params}, indent=2, sort_keys=True,
            ) + "\n",
            encoding="utf-8",
        )

    @classmethod
    def load(cls, directory: str | Path) -> IsolationForestLayer:
        source = Path(directory)
        meta = json.loads((source / "isolation_forest.json").read_text(encoding="utf-8"))
        layer = cls(meta["params"], meta["seed"], meta["features"])
        stored = joblib.load(source / "isolation_forest.joblib")
        layer.model, layer.calibration = stored["model"], stored["calibration"]
        return layer
