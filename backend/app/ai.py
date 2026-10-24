"""The AI service: base forecaster + crowd mean + learned blend, versioned.

This is the honest version of "players train the AI":

* the **base forecaster** is a Ridge model fit on historical windows and does
  not change when people play;
* the **crowd curve** is a running pointwise mean of every drawing on a round,
  which only exists because people played;
* the **blend weight** ``w`` per round type is re-fit from real outcomes every
  ``RETRAIN_EVERY`` drawings, and that is the part human play actually moves.

Each retrain writes an ``ai_versions`` row carrying model-only, crowd-only and
blend RMSE on a held-out split, which is what the dashboard charts.
"""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from model import blend as blend_mod
from model.forecaster import MODEL_PATH, ForecastBank

from . import config
from .models import AIVersion, Drawing, Round

TRAINING_PATH = config.ROUNDS_DIR / "training.json"
EVAL_FRAC = 0.3          # share of crowd-backed rounds held out of the w fit


def _eval_bucket(round_id: str) -> bool:
    """Stable per-round hold-out assignment, so versions stay comparable.

    Hashed with sha1 rather than ``hash()``, whose string seed is randomised
    per process -- the split has to survive a server restart.
    """
    digest = hashlib.sha1(round_id.encode()).hexdigest()[:8]
    return int(digest, 16) / 0xFFFFFFFF < EVAL_FRAC


class AIService:
    def __init__(self) -> None:
        self.bank = ForecastBank.load()
        self.weights: dict[str, float] = {}
        self.version: int = 0
        self.drawings_at_version: int = 0
        self.last_retrain: dict | None = None
        self._lock = threading.Lock()
        self._retraining = False

    # --- lifecycle --------------------------------------------------------
    def load_state(self, db: Session) -> None:
        row = db.scalars(select(AIVersion).order_by(AIVersion.version.desc())).first()
        if row is not None:
            self.version = row.version
            self.weights = row.weights
            self.drawings_at_version = row.drawings_seen
        if not self.bank.is_trained():
            print("[ai] no trained forecaster found; predictions fall back to "
                  "persistence until `python -m model.train` runs", flush=True)

    def weight_for(self, round_type: str) -> float:
        return float(self.weights.get(round_type, blend_mod.DEFAULT_W))

    # --- prediction -------------------------------------------------------
    def model_curve(self, payload: dict) -> list[float]:
        return [float(v) for v in self.bank.predict(payload)]

    def curves(self, rnd: Round) -> tuple[list[float], list[float], list[float] | None, int]:
        """``(ai_curve, model_curve, crowd_curve, crowd_n)`` for one round."""
        payload = rnd.payload
        model = self.bank.predict(payload)
        crowd = rnd.crowd_mean
        if crowd is None or rnd.crowd_n < config.MIN_CROWD:
            return ([float(v) for v in model], [float(v) for v in model],
                    ([float(v) for v in crowd] if crowd else None), rnd.crowd_n)
        w = self.weight_for(rnd.type)
        ai = blend_mod.blend(model, crowd, w)
        return ([float(v) for v in ai], [float(v) for v in model],
                [float(v) for v in crowd], rnd.crowd_n)

    # --- retraining -------------------------------------------------------
    def should_retrain(self, total_drawings: int) -> bool:
        return (total_drawings - self.drawings_at_version) >= config.RETRAIN_EVERY

    def _maybe_refit_base(self) -> bool:
        """Re-fit the base forecaster only when the pipeline produced new data."""
        try:
            if not TRAINING_PATH.exists():
                return False
            fresher = (not Path(MODEL_PATH).exists()
                       or TRAINING_PATH.stat().st_mtime > Path(MODEL_PATH).stat().st_mtime)
            if not fresher:
                return False
            from model.train import train
            self.bank = train(verbose=False)
            return True
        except Exception as exc:  # noqa: BLE001 - never take gameplay down
            print(f"[ai] base refit skipped ({type(exc).__name__}: {exc})", flush=True)
            return False

    def retrain(self, db: Session, *, note: str = "", force: bool = False) -> dict | None:
        """Re-fit blend weights (and the base model if data changed).

        Safe to call from a background task; concurrent calls are collapsed.
        """
        with self._lock:
            if self._retraining:
                return None
            self._retraining = True
        try:
            total = db.scalar(select(func.count(Drawing.id))) or 0
            if not force and not self.should_retrain(total):
                return None

            base_refit = self._maybe_refit_base()

            rounds = db.scalars(
                select(Round).where(Round.crowd_n >= config.MIN_CROWD)).all()
            fit_samples: dict[str, list[tuple]] = {}
            eval_rows: list[tuple[str, np.ndarray, np.ndarray, np.ndarray]] = []

            for rnd in rounds:
                payload = rnd.payload
                truth = np.asarray(payload["hidden"], dtype=float)
                crowd = np.asarray(rnd.crowd_mean, dtype=float)
                model = self.bank.predict(payload)
                if _eval_bucket(rnd.id):
                    eval_rows.append((rnd.type, model, crowd, truth))
                else:
                    fit_samples.setdefault(rnd.type, []).append((model, crowd, truth))

            fitted = blend_mod.fit_weights_by_type(fit_samples)
            new_weights = dict(self.weights)
            for kind, info in fitted.items():
                if info["n"] >= config.BLEND_MIN_ROUNDS:
                    new_weights[kind] = info["w"]

            metrics = self._evaluate(eval_rows, new_weights)
            if metrics["n_eval"] == 0:
                # Nothing held out yet: report on the fit set so the first few
                # versions still have numbers to chart.
                flat = [(k, m, c, t) for k, rows in fit_samples.items()
                        for (m, c, t) in rows]
                metrics = self._evaluate(flat, new_weights)

            self.weights = new_weights
            self.version += 1
            self.drawings_at_version = total
            row = AIVersion(
                version=self.version,
                created_at=datetime.now(timezone.utc),
                drawings_seen=total,
                new_drawings=total - (db.scalar(select(func.max(AIVersion.drawings_seen))) or 0),
                weights_json=json.dumps(new_weights),
                rmse_model=metrics["rmse_model"],
                rmse_crowd=metrics["rmse_crowd"],
                rmse_blend=metrics["rmse_blend"],
                n_eval=metrics["n_eval"],
                base_refit=base_refit,
                note=note or ("base model refit" if base_refit else "blend weights refit"),
            )
            db.add(row)
            db.commit()

            self.last_retrain = {
                "version": self.version, "weights": new_weights,
                "per_type": {k: {"w": v["w"], "n": v["n"]} for k, v in fitted.items()},
                **metrics,
            }
            print(f"[ai] v{self.version} deployed  w={new_weights}  "
                  f"model={metrics['rmse_model']} crowd={metrics['rmse_crowd']} "
                  f"blend={metrics['rmse_blend']} (n={metrics['n_eval']})", flush=True)
            return self.last_retrain
        finally:
            self._retraining = False

    @staticmethod
    def _evaluate(rows, weights: dict[str, float]) -> dict:
        if not rows:
            return {"rmse_model": None, "rmse_crowd": None,
                    "rmse_blend": None, "n_eval": 0}
        m_err, c_err, b_err = [], [], []
        for kind, model, crowd, truth in rows:
            w = float(weights.get(kind, blend_mod.DEFAULT_W))
            blended = blend_mod.blend(model, crowd, w)
            m_err.append((model - truth) ** 2)
            c_err.append((crowd - truth) ** 2)
            b_err.append((blended - truth) ** 2)
        rms = lambda e: round(float(np.sqrt(np.mean(np.vstack(e)))), 6)  # noqa: E731
        return {"rmse_model": rms(m_err), "rmse_crowd": rms(c_err),
                "rmse_blend": rms(b_err), "n_eval": len(rows)}

    # --- crowd ------------------------------------------------------------
    @staticmethod
    def update_crowd(rnd: Round, curve: list[float]) -> None:
        """Fold one drawing into the round's running pointwise mean."""
        total = rnd.crowd_sum
        if total is None or len(total) != len(curve):
            total = [0.0] * len(curve)
            rnd.crowd_n = 0
        rnd.crowd_sum_json = json.dumps([a + b for a, b in zip(total, curve)])
        rnd.crowd_n += 1
        rnd.play_count += 1


ai_service = AIService()
