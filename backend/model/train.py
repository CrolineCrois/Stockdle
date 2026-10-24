"""Fit the base forecasters on the historical training windows.

    python -m model.train

Reports held-out RMSE per round type against two naive baselines
(persistence = flat line, drift = continue the recent slope), plus the error on
the *game* rounds, which the model has never seen.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from . import features as F
from .forecaster import ForecastBank, Forecaster, drift_curve, persistence_curve

ROUNDS_DIR = Path(__file__).resolve().parents[2] / "data" / "rounds"


def _load(name: str) -> list[dict]:
    path = ROUNDS_DIR / name
    if not path.exists():
        raise SystemExit(f"{path} missing - run `python -m pipeline.build_rounds` first")
    return json.loads(path.read_text(encoding="utf-8"))


def train(seed: int = 0, verbose: bool = True) -> ForecastBank:
    training = _load("training.json")
    rounds = _load("rounds.json")

    by_model: dict[str, list[dict]] = {}
    for rec in training:
        by_model.setdefault(F.model_key(rec["type"]), []).append(rec)

    bank = ForecastBank()
    for name, recs in sorted(by_model.items()):
        model = Forecaster(name=name)
        metrics = model.fit(recs, seed=seed)
        bank.models[name] = model
        if verbose:
            print(f"  {name:<12} n={metrics['n_train']:>5}  alpha={metrics['alpha']:>6}  "
                  f"rmse={metrics['rmse_model']:.4f}  "
                  f"persistence={metrics['rmse_persistence']:.4f}  "
                  f"drift={metrics['rmse_drift']:.4f}  "
                  f"skill={metrics['skill_vs_persistence']:+.1%}")

    # Unseen-data check: the 200 playable rounds share no index with training.
    if verbose:
        print("\n  held-out game rounds (never trained on):")
        by_type: dict[str, list[dict]] = {}
        for r in rounds:
            by_type.setdefault(r["type"], []).append(r)
        for kind, recs in sorted(by_type.items()):
            truth = np.vstack([r["hidden"] for r in recs])
            pred = bank.get(kind).predict_many(recs)
            flat = np.vstack([persistence_curve(r) for r in recs])
            drift = np.vstack([drift_curve(r) for r in recs])
            rm = float(np.sqrt(np.mean((pred - truth) ** 2)))
            rp = float(np.sqrt(np.mean((flat - truth) ** 2)))
            rd = float(np.sqrt(np.mean((drift - truth) ** 2)))
            print(f"  {kind:<12} n={len(recs):>4}  model={rm:.4f}  "
                  f"persistence={rp:.4f}  drift={rd:.4f}  "
                  f"skill={1 - rm / rp:+.1%}")

    bank.save()
    if verbose:
        print(f"\n  saved -> {bank.save()}")
    return bank


if __name__ == "__main__":
    print("Training TAPE base forecasters\n")
    train()
