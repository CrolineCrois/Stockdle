"""The crowd-blend layer: where player drawings actually change the AI.

``prediction = w * model + (1 - w) * crowd``

``w`` is fit per round type by grid search over [0, 1]. A round only enters the
fit once at least ``MIN_CROWD`` people have drawn it; below that the crowd mean
is too noisy and the blend falls back to the model alone.
"""

from __future__ import annotations

import numpy as np

GRID = np.round(np.arange(0.0, 1.0001, 0.05), 3)
DEFAULT_W = 1.0            # no crowd evidence yet -> trust the model


def blend(model_curve, crowd_curve, w: float) -> np.ndarray:
    m = np.asarray(model_curve, dtype=float)
    if crowd_curve is None:
        return m
    c = np.asarray(crowd_curve, dtype=float)
    return np.clip(w * m + (1.0 - w) * c, 0.0, 1.0)


def _rmse(pred: np.ndarray, truth: np.ndarray) -> float:
    return float(np.sqrt(np.mean((pred - truth) ** 2)))


def fit_weight(model_curves, crowd_curves, truths) -> tuple[float, dict]:
    """Grid-search the single ``w`` that minimises RMSE over these rounds."""
    M = np.vstack([np.asarray(c, dtype=float) for c in model_curves])
    C = np.vstack([np.asarray(c, dtype=float) for c in crowd_curves])
    T = np.vstack([np.asarray(c, dtype=float) for c in truths])

    best_w, best_err = DEFAULT_W, float("inf")
    curve = []
    for w in GRID:
        err = _rmse(np.clip(w * M + (1.0 - w) * C, 0.0, 1.0), T)
        curve.append((float(w), round(err, 6)))
        if err < best_err:
            best_w, best_err = float(w), err
    return best_w, {
        "w": best_w,
        "rmse_blend": round(best_err, 6),
        "rmse_model": round(_rmse(M, T), 6),
        "rmse_crowd": round(_rmse(C, T), 6),
        "n": int(len(T)),
        "sweep": curve,
    }


def fit_weights_by_type(samples: dict[str, list[tuple]]) -> dict[str, dict]:
    """``samples[type] = [(model_curve, crowd_curve, truth), ...]``."""
    out: dict[str, dict] = {}
    for kind, rows in samples.items():
        if not rows:
            continue
        models, crowds, truths = zip(*rows)
        _, info = fit_weight(models, crowds, truths)
        out[kind] = info
    return out
