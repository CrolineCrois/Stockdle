"""Round scoring.

Everything here operates on normalised 0-1 curves of exactly 50 points, so a
score means the same thing whether the round was a load curve or a stock tape.
The volatility normaliser (``sigma``) is what makes that true: a quiet series
demands a tight line, a jumpy one forgives more.

    base   = 100 * exp(-K * err),  err = RMSE / max(sigma * SIGMA_MULT, FLOOR)
    total  = (base + bonuses) * streak multiplier

Run ``pytest backend/tests/test_scoring.py`` for the unit tests, and
``python -m scoring --calibrate`` for the tuning report.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Sequence

import numpy as np

CURVE_LEN = 50

# --- tuned constants ------------------------------------------------------
K = 1.2                   # error -> score decay
SIGMA_MULT = 9.0          # how many step-sigmas of error are "one unit"
SIGMA_FLOOR = 0.09        # stops a dead-flat truth from making scoring brutal
SIGMA_EPS = 1e-4          # floor on sigma itself

BONUS_TURNING_POINT = 25
BONUS_DIRECTION = 10
BONUS_BEAT_AI = 20
BONUS_BEAT_CROWD = 20

BULLSEYE_AT = 95          # base score that triggers the bullseye animation
STREAK_AT = 75            # base score that keeps a streak alive
STREAK_STEP = 0.1
STREAK_CAP = 2.0

TURN_TOLERANCE = 3        # x-steps
TURN_PROMINENCE = 0.35    # fraction of the hidden range a peak must clear
TURN_EDGE_GUARD = 3       # extremum must be this far from either edge
FLAT_RANGE = 0.05         # hidden ranges below this have no turning point
DIRECTION_EPS = 0.01      # |end - start| below this counts as "flat"


@dataclass
class Bonus:
    key: str
    label: str
    points: int


@dataclass
class ScoreBreakdown:
    base: int
    total: int
    rmse: float
    sigma: float
    err: float
    multiplier: float
    streak_before: int
    streak_after: int
    bullseye: bool
    bonuses: list[Bonus] = field(default_factory=list)
    ai_rmse: float | None = None
    crowd_rmse: float | None = None
    turning_point: dict | None = None

    @property
    def bonus_points(self) -> int:
        return sum(b.points for b in self.bonuses)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["bonus_points"] = self.bonus_points
        return d


# --- primitives -----------------------------------------------------------
def _as_curve(values: Sequence[float], name: str = "curve") -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    if arr.shape != (CURVE_LEN,):
        raise ValueError(f"{name} must be {CURVE_LEN} points, got {arr.shape}")
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"{name} contains NaN or infinity")
    return arr


def rmse(a: Sequence[float], b: Sequence[float]) -> float:
    x, y = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    return float(np.sqrt(np.mean((x - y) ** 2)))


def step_sigma(truth: Sequence[float]) -> float:
    """Standard deviation of the truth's first differences, floored."""
    diffs = np.diff(np.asarray(truth, dtype=float))
    return max(float(np.std(diffs)), SIGMA_EPS)


def base_score(player: Sequence[float], truth: Sequence[float]) -> tuple[int, float, float, float]:
    """Return ``(base, rmse, sigma, err)``."""
    p, t = _as_curve(player, "player"), _as_curve(truth, "truth")
    e = rmse(p, t)
    sigma = step_sigma(t)
    err = e / max(sigma * SIGMA_MULT, SIGMA_FLOOR)
    score = int(round(100.0 * math.exp(-K * err)))
    return max(0, min(100, score)), e, sigma, err


def find_turning_point(truth: Sequence[float]) -> dict | None:
    """The hidden curve's dominant interior extremum, if it has a clear one.

    Prominence is measured against the *higher* (for a peak) or *lower* (for a
    trough) of the two endpoints, so a monotone ramp -- whose max sits at the
    last point -- never counts as a turning point.
    """
    t = np.asarray(truth, dtype=float)
    span = float(t.max() - t.min())
    if span < FLAT_RANGE:
        return None

    lo_guard, hi_guard = TURN_EDGE_GUARD, len(t) - 1 - TURN_EDGE_GUARD
    best: dict | None = None

    i_max = int(np.argmax(t))
    if lo_guard <= i_max <= hi_guard:
        prom = (t[i_max] - max(t[0], t[-1])) / span
        if prom >= TURN_PROMINENCE:
            best = {"kind": "max", "index": i_max, "prominence": round(float(prom), 4)}

    i_min = int(np.argmin(t))
    if lo_guard <= i_min <= hi_guard:
        prom = (min(t[0], t[-1]) - t[i_min]) / span
        if prom >= TURN_PROMINENCE and (best is None or prom > best["prominence"]):
            best = {"kind": "min", "index": i_min, "prominence": round(float(prom), 4)}

    return best


def _direction(curve: np.ndarray) -> int:
    delta = float(curve[-1] - curve[0])
    if abs(delta) < DIRECTION_EPS:
        return 0
    return 1 if delta > 0 else -1


def streak_multiplier(streak: int) -> float:
    return min(1.0 + STREAK_STEP * max(0, streak), STREAK_CAP)


# --- the whole round ------------------------------------------------------
def score_round(
    player: Sequence[float],
    truth: Sequence[float],
    *,
    visible: Sequence[float] | None = None,
    ai_curve: Sequence[float] | None = None,
    crowd_curve: Sequence[float] | None = None,
    crowd_n: int = 0,
    streak: int = 0,
) -> ScoreBreakdown:
    """Score one submitted drawing.

    ``visible`` is accepted for continuity checks and future use; it does not
    currently change the score. ``crowd_n`` is how many drawings the crowd mean
    is built from -- fewer than 3 and the crowd comparison is skipped entirely.
    """
    p = _as_curve(player, "player")
    t = _as_curve(truth, "truth")
    if visible is not None and len(visible) == 0:
        raise ValueError("visible must be non-empty when provided")

    base, err_rmse, sigma, err = base_score(p, t)
    bonuses: list[Bonus] = []

    turn = find_turning_point(t)
    if turn is not None:
        player_idx = int(np.argmax(p) if turn["kind"] == "max" else np.argmin(p))
        turn = {**turn, "player_index": player_idx,
                "hit": abs(player_idx - turn["index"]) <= TURN_TOLERANCE}
        if turn["hit"]:
            label = "Called the peak" if turn["kind"] == "max" else "Called the dip"
            bonuses.append(Bonus("turning_point", label, BONUS_TURNING_POINT))

    if _direction(p) == _direction(t):
        bonuses.append(Bonus("direction", "Right direction", BONUS_DIRECTION))

    ai_rmse = None
    if ai_curve is not None:
        ai_rmse = rmse(_as_curve(ai_curve, "ai_curve"), t)
        if err_rmse < ai_rmse:
            bonuses.append(Bonus("beat_ai", "Beat the AI", BONUS_BEAT_AI))

    crowd_rmse = None
    if crowd_curve is not None and crowd_n >= 3:
        crowd_rmse = rmse(_as_curve(crowd_curve, "crowd_curve"), t)
        if err_rmse < crowd_rmse:
            bonuses.append(Bonus("beat_crowd", "Beat the crowd", BONUS_BEAT_CROWD))

    multiplier = streak_multiplier(streak)
    subtotal = base + sum(b.points for b in bonuses)
    total = int(round(subtotal * multiplier))
    streak_after = streak + 1 if base >= STREAK_AT else 0

    return ScoreBreakdown(
        base=base,
        total=total,
        rmse=round(err_rmse, 6),
        sigma=round(sigma, 6),
        err=round(err, 6),
        multiplier=round(multiplier, 2),
        streak_before=streak,
        streak_after=streak_after,
        bullseye=base >= BULLSEYE_AT,
        bonuses=bonuses,
        ai_rmse=round(ai_rmse, 6) if ai_rmse is not None else None,
        crowd_rmse=round(crowd_rmse, 6) if crowd_rmse is not None else None,
        turning_point=turn,
    )


def skipped_round(streak: int = 0) -> ScoreBreakdown:
    """A round the player ran out of time on: zero, and the streak dies."""
    return ScoreBreakdown(base=0, total=0, rmse=0.0, sigma=0.0, err=0.0,
                          multiplier=streak_multiplier(streak), streak_before=streak,
                          streak_after=0, bullseye=False, bonuses=[])


# --- calibration ----------------------------------------------------------
def _calibrate(path: str | None = None) -> None:
    """Score simulated 'sloppy / decent / great' players on the real rounds."""
    import json
    from pathlib import Path

    rounds_path = Path(path or Path(__file__).resolve().parents[1]
                       / "data" / "rounds" / "rounds.json")
    rounds = json.loads(rounds_path.read_text(encoding="utf-8"))
    rng = np.random.default_rng(1)

    # A "player" is modelled as the truth plus smoothed noise scaled by the
    # round's own step volatility, so the tiers mean the same thing everywhere.
    tiers = {"sloppy": 3.0, "decent": 1.2, "great": 0.35}
    print(f"{'type':<12}{'n':>5}  " + "  ".join(f"{k:>18}" for k in tiers))
    by_type: dict[str, list] = {}
    for r in rounds:
        by_type.setdefault(r["type"], []).append(r)

    for kind, rs in sorted(by_type.items()):
        cells = []
        for _, noise in tiers.items():
            scores = []
            for r in rs:
                t = np.asarray(r["hidden"])
                sigma = step_sigma(t)
                raw = rng.normal(0, sigma * noise, CURVE_LEN)
                smooth = np.convolve(raw, np.ones(7) / 7, mode="same")
                scores.append(base_score(np.clip(t + np.cumsum(smooth) * 0.6, 0, 1), t)[0])
            cells.append(f"{np.mean(scores):>7.1f} ±{np.std(scores):<5.1f}"
                         f"p90={np.percentile(scores, 90):<3.0f}")
        print(f"{kind:<12}{len(rs):>5}  " + "  ".join(f"{c:>18}" for c in cells))


if __name__ == "__main__":
    import sys
    if "--calibrate" in sys.argv:
        _calibrate()
    else:
        print(__doc__)
