"""The base forecaster: one multi-output Ridge per round type.

Ridge is the right tool here -- 50 correlated outputs, a few hundred to a few
thousand training windows, and a hard requirement that a prediction comes back
in under a millisecond so a submit never waits on it. Alpha is picked by a
small grid search against a held-out tail of the training windows.

Predictions are returned already re-anchored and clipped into the 0-1 canvas,
so the caller can hand them straight to the client.
"""

from __future__ import annotations

import json
import pickle
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from . import features as F

MODEL_DIR = Path(__file__).resolve().parents[2] / "data" / "models"
MODEL_DIR.mkdir(parents=True, exist_ok=True)
MODEL_PATH = MODEL_DIR / "forecasters.pkl"
METRICS_PATH = MODEL_DIR / "base_metrics.json"

ALPHA_GRID = (0.1, 1.0, 3.0, 10.0, 30.0, 100.0, 300.0)
VALID_FRAC = 0.2


def persistence_curve(record: dict) -> np.ndarray:
    """The naive baseline every forecast has to beat: a flat line."""
    return np.full(50, F.anchor_of(record), dtype=float)


def drift_curve(record: dict) -> np.ndarray:
    """Second baseline: continue the last-10-step slope."""
    visible = np.asarray(record["visible"], dtype=float)
    slope = F._slope(visible[-10:])
    return np.clip(visible[-1] + slope * np.arange(1, 51), 0.0, 1.0)


@dataclass
class Forecaster:
    """Per-round-type model plus the metadata the dashboard reports."""

    name: str
    pipeline: Pipeline | None = None
    alpha: float | None = None
    n_train: int = 0
    metrics: dict = field(default_factory=dict)

    def fit(self, records: list[dict], seed: int = 0) -> dict:
        X, Y = F.build_matrix(records)
        n = len(records)
        cut = max(1, int(n * (1 - VALID_FRAC)))
        # Chronological-ish split: training windows arrive in series order, so
        # a tail split keeps the validation set out of the fitted region.
        Xtr, Ytr, Xva, Yva = X[:cut], Y[:cut], X[cut:], Y[cut:]
        if len(Xva) == 0:
            Xva, Yva = Xtr, Ytr

        best = (None, None, float("inf"))
        for alpha in ALPHA_GRID:
            pipe = Pipeline([("scale", StandardScaler()),
                             ("ridge", Ridge(alpha=alpha, random_state=seed))])
            pipe.fit(Xtr, Ytr)
            err = float(np.sqrt(np.mean((pipe.predict(Xva) - Yva) ** 2)))
            if err < best[2]:
                best = (pipe, alpha, err)

        # Refit the winner on everything.
        self.alpha = best[1]
        self.pipeline = Pipeline([("scale", StandardScaler()),
                                  ("ridge", Ridge(alpha=self.alpha, random_state=seed))])
        self.pipeline.fit(X, Y)
        self.n_train = n

        va_records = records[cut:] or records
        self.metrics = {
            "n_train": n,
            "n_valid": len(va_records),
            "alpha": self.alpha,
            "rmse_model": round(best[2], 6),
            "rmse_persistence": round(float(np.sqrt(np.mean(
                np.vstack([persistence_curve(r) - np.asarray(r["hidden"])
                           for r in va_records]) ** 2))), 6),
            "rmse_drift": round(float(np.sqrt(np.mean(
                np.vstack([drift_curve(r) - np.asarray(r["hidden"])
                           for r in va_records]) ** 2))), 6),
        }
        base = self.metrics["rmse_persistence"]
        self.metrics["skill_vs_persistence"] = round(
            1.0 - self.metrics["rmse_model"] / base, 4) if base else 0.0
        return self.metrics

    def predict(self, record: dict) -> np.ndarray:
        anchor = F.anchor_of(record)
        if self.pipeline is None:
            return np.full(50, anchor, dtype=float)
        delta = self.pipeline.predict(F.extract(record).reshape(1, -1))[0]
        return np.clip(anchor + delta, 0.0, 1.0)

    def predict_many(self, records: list[dict]) -> np.ndarray:
        if not records:
            return np.zeros((0, 50))
        if self.pipeline is None:
            return np.vstack([persistence_curve(r) for r in records])
        X = np.vstack([F.extract(r) for r in records])
        anchors = np.asarray([F.anchor_of(r) for r in records]).reshape(-1, 1)
        return np.clip(anchors + self.pipeline.predict(X), 0.0, 1.0)


class ForecastBank:
    """All per-type forecasters, loaded once and shared by the API."""

    def __init__(self, models: dict[str, Forecaster] | None = None):
        self.models: dict[str, Forecaster] = models or {}

    def get(self, round_type: str) -> Forecaster:
        name = F.model_key(round_type)
        return self.models.get(name) or Forecaster(name=name)

    def predict(self, record: dict) -> np.ndarray:
        return self.get(record["type"]).predict(record)

    def is_trained(self) -> bool:
        return any(m.pipeline is not None for m in self.models.values())

    # --- persistence ------------------------------------------------------
    def save(self, path: Path = MODEL_PATH) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as fh:
            pickle.dump(self.models, fh, protocol=pickle.HIGHEST_PROTOCOL)
        METRICS_PATH.write_text(
            json.dumps({k: m.metrics for k, m in self.models.items()}, indent=2),
            encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: Path = MODEL_PATH) -> "ForecastBank":
        try:
            with open(path, "rb") as fh:
                return cls(pickle.load(fh))
        except Exception:  # noqa: BLE001 - an untrained bank still plays
            return cls({})
