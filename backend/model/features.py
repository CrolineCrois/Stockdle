"""Turn a round (or training window) into a model feature vector.

Everything is expressed *relative to the last visible point* (the anchor), and
the model's target is likewise ``hidden - anchor``. That makes the features
level-invariant and guarantees the prediction starts where the visible line
stopped, which is also what the canvas needs.

Shape:

    [ 30 anchored lags | 9 shape stats | type-specific block ]
"""

from __future__ import annotations

import math

import numpy as np

from .text import headline_feature_dim, headline_features

LAGS = 30
SHAPE_DIM = 9
ROUND_TYPES = ("electricity", "stock", "trends")
MODEL_FOR_TYPE = {"electricity": "electricity", "stock": "stock", "trends": "trends"}


def _cyc(value: float, period: float) -> tuple[float, float]:
    angle = 2.0 * math.pi * (float(value) / period)
    return math.sin(angle), math.cos(angle)


def _slope(arr: np.ndarray) -> float:
    if arr.size < 2:
        return 0.0
    x = np.arange(arr.size, dtype=float)
    return float(np.polyfit(x, arr, 1)[0])


def shape_features(visible: np.ndarray) -> np.ndarray:
    """Nine level-invariant descriptors of the visible run-up."""
    anchor = float(visible[-1])
    rel = visible - anchor
    diffs = np.diff(visible)
    return np.asarray([
        anchor,                                   # where on the canvas we are
        _slope(visible[-10:]),
        _slope(visible[-30:]),
        _slope(visible),
        float(np.std(diffs)) if diffs.size else 0.0,
        float(np.std(diffs[-20:])) if diffs.size >= 2 else 0.0,
        float(rel.max()),
        float(rel.min()),
        float(rel.mean()),
    ], dtype=float)


def _electricity_block(feat: dict) -> np.ndarray:
    hour_s, hour_c = _cyc(feat.get("hour", 12), 24)
    dow_s, dow_c = _cyc(feat.get("dow", 2), 7)
    mon_s, mon_c = _cyc(feat.get("month", 6) - 1, 12)
    t_now = float(feat.get("temp_now", 70.0))
    t_hi = float(feat.get("temp_hi", 70.0))
    t_lo = float(feat.get("temp_lo", 70.0))
    t_vis = float(feat.get("temp_mean_vis", 70.0))
    return np.asarray([
        hour_s, hour_c, dow_s, dow_c, mon_s, mon_c,
        t_now / 100.0, t_hi / 100.0, t_lo / 100.0,
        (t_hi - t_now) / 50.0,                     # how much hotter it gets
        max(t_hi - 68.0, 0.0) / 50.0,              # forecast cooling degrees
        max(58.0 - t_lo, 0.0) / 50.0,              # forecast heating degrees
        (t_now - t_vis) / 50.0,                    # warming vs the visible window
        1.0 if feat.get("dow", 0) >= 5 else 0.0,   # weekend
    ], dtype=float)


ELECTRICITY_DIM = 14


def _stock_block(feat: dict) -> np.ndarray:
    text = headline_features(feat.get("headline", "") or "")
    age = float(feat.get("age_steps", 999))
    hour_s, hour_c = _cyc(feat.get("hour", 12), 24)
    dow_s, dow_c = _cyc(feat.get("dow", 2), 7)
    extra = np.asarray([
        min(age, 300.0) / 300.0,
        1.0 if age <= 5 else 0.0,                  # the news just broke
        hour_s, hour_c, dow_s, dow_c,
    ], dtype=float)
    return np.concatenate([text, extra])


def _stock_dim() -> int:
    return headline_feature_dim() + 6


def _trends_block(feat: dict) -> np.ndarray:
    wk_s, wk_c = _cyc(feat.get("week", 26), 52)
    mo_s, mo_c = _cyc(feat.get("month", 6) - 1, 12)
    # A second harmonic lets Ridge express narrow seasonal spikes.
    wk2_s, wk2_c = _cyc(2 * feat.get("week", 26), 52)
    return np.asarray([wk_s, wk_c, mo_s, mo_c, wk2_s, wk2_c], dtype=float)


TRENDS_DIM = 6

_BLOCKS = {"electricity": _electricity_block, "stock": _stock_block,
           "trends": _trends_block}


def model_key(round_type: str) -> str:
    return MODEL_FOR_TYPE.get(round_type, "stock")


def feature_dim(model_name: str) -> int:
    extra = {"electricity": ELECTRICITY_DIM, "trends": TRENDS_DIM,
             "stock": _stock_dim()}[model_name]
    return LAGS + SHAPE_DIM + extra


def extract(record: dict) -> np.ndarray:
    """Feature vector for one round or training window."""
    visible = np.asarray(record["visible"], dtype=float)
    anchor = float(visible[-1])
    lags = visible[-LAGS:] - anchor
    if lags.size < LAGS:                            # defensive: short visible
        lags = np.pad(lags, (LAGS - lags.size, 0), mode="edge")
    name = model_key(record["type"])
    block = _BLOCKS[name](record.get("feat") or {})
    return np.concatenate([lags, shape_features(visible), block])


def target(record: dict) -> np.ndarray:
    """What the model predicts: the hidden curve as a delta from the anchor."""
    anchor = float(np.asarray(record["visible"], dtype=float)[-1])
    return np.asarray(record["hidden"], dtype=float) - anchor


def anchor_of(record: dict) -> float:
    return float(np.asarray(record["visible"], dtype=float)[-1])


def build_matrix(records: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    X = np.vstack([extract(r) for r in records])
    Y = np.vstack([target(r) for r in records])
    return X, Y
