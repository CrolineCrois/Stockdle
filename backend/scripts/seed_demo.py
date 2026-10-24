"""Populate the database with simulated play so a cold demo looks alive.

Creates ~40 simulated players with distinct personalities, has them draw ~600
rounds, and triggers a retrain every ``RETRAIN_EVERY`` drawings so the version
history chart has a real shape by the time anyone opens it.

Every simulated player is flagged ``is_bot=True`` and the leaderboard labels
them "sim" — the demo should not quietly pass synthetic play off as a crowd.

    python -m scripts.seed_demo              # add the demo cohort
    python -m scripts.seed_demo --reset      # wipe play data first
    python -m scripts.seed_demo --drawings 900 --players 50
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import uuid
from datetime import datetime, timedelta, timezone

import numpy as np
from sqlalchemy import delete, func, select

import scoring
from app import config
from app.ai import ai_service
from app.db import SessionLocal, init_db, load_rounds_catalogue
from app.models import AIVersion, Drawing, Player, Round

FIRST = ["chart", "tape", "delta", "vega", "gamma", "quant", "pixel", "ridge", "sigma",
         "ember", "nova", "atlas", "pepper", "cobalt", "zephyr", "mango", "orbit",
         "pluto", "rook", "flint"]
LAST = ["goblin", "wizard", "hands", "oracle", "ghost", "badger", "fox", "otter",
        "crane", "moth", "lark", "bear", "wolf", "newt", "koi"]


def crowd_misread(payload: dict) -> np.ndarray:
    """The error every simulated human on a round makes *together*.

    This is the difference between a realistic simulation and a useless one. If
    each player were truth-plus-independent-noise, the crowd mean would converge
    on the truth and "the crowd beats the model" would be an artifact of the
    simulator rather than a finding.

    Real forecasters share a bias: they extrapolate the recent slope and
    under-weight mean reversion and seasonality. So every player is pulled part
    of the way from the truth toward the naive drift line, by a round-specific
    amount. The crowd mean therefore sits somewhere wrong-but-informative, which
    is exactly the regime where blending with a model pays.
    """
    truth = np.asarray(payload["hidden"], dtype=float)
    visible = np.asarray(payload["visible"], dtype=float)
    anchor = float(visible[-1])
    slope = float(np.polyfit(np.arange(10), visible[-10:], 1)[0])
    naive = anchor + slope * np.arange(1, scoring.CURVE_LEN + 1)
    # Deterministic per round (sha1, not hash(), whose string seed is
    # randomised per process) so a round's crowd is consistent across runs.
    digest = hashlib.sha1(str(payload.get("id", "")).encode()).hexdigest()[:8]
    alpha = 0.30 + 0.30 * ((int(digest, 16) % 97) / 97.0)
    return alpha * (np.clip(naive, 0.0, 1.0) - truth)


class Persona:
    """A simulated player.

    ``skill`` scales how closely they track the truth; ``headline_gain`` is how
    hard they lean into a headline (the overreaction we want the dashboard to
    surface); ``drift`` is a constant vertical bias; ``smooth`` is how clean
    their hand is; ``herding`` is how much of the shared crowd misread they
    pick up (contrarians sit below 1).
    """

    def __init__(self, rng: np.random.Generator, idx: int):
        tier = rng.random()
        if tier < 0.18:                     # the sharks
            self.skill, self.smooth = rng.uniform(0.35, 0.6), 9
        elif tier < 0.72:                   # the median player
            self.skill, self.smooth = rng.uniform(0.9, 1.5), 6
        else:                               # the wild ones
            self.skill, self.smooth = rng.uniform(1.8, 3.0), 4
        # Most people overreact to a headline; a few are contrarian.
        self.headline_gain = float(rng.normal(1.0, 0.9))
        self.drift = float(rng.normal(0.0, 0.012))
        self.herding = float(np.clip(rng.normal(1.0, 0.35), 0.1, 1.8))
        self.name = f"{FIRST[idx % len(FIRST)]}_{LAST[(idx * 7) % len(LAST)]}"
        if idx >= len(FIRST):
            self.name += str(idx // len(FIRST) + 1)

    def draw(self, rng: np.random.Generator, payload: dict) -> list[float]:
        truth = np.asarray(payload["hidden"], dtype=float)
        visible = np.asarray(payload["visible"], dtype=float)
        anchor = float(visible[-1])
        sigma = scoring.step_sigma(truth)

        # Start from the truth, then degrade it the way a hand does: a smoothed
        # random walk away from it, anchored at the cut point.
        raw = rng.normal(0.0, sigma * self.skill, scoring.CURVE_LEN)
        kernel = np.ones(self.smooth) / self.smooth
        wobble = np.cumsum(np.convolve(raw, kernel, mode="same")) * 0.6
        curve = truth + crowd_misread(payload) * self.herding + wobble + self.drift

        # Headline rounds: lean into the story.
        headline = (payload.get("feat") or {}).get("headline") or ""
        if payload["type"] == "stock" and headline:
            from model.text import lexical_features
            tone = lexical_features(headline)[3]          # VADER compound
            push = tone * self.headline_gain * sigma * 6.0
            curve = curve + push * np.linspace(0.0, 1.0, scoring.CURVE_LEN)

        # Hands start at the cut point, not in mid-air.
        curve[0] = anchor + (curve[0] - anchor) * 0.25
        return [float(v) for v in np.clip(curve, 0.0, 1.0)]


def reset(db) -> None:
    db.execute(delete(Drawing))
    db.execute(delete(AIVersion))
    db.execute(delete(Player))
    for rnd in db.scalars(select(Round)).all():
        rnd.crowd_sum_json = ""
        rnd.crowd_n = 0
        rnd.play_count = 0
    db.commit()
    ai_service.version = 0
    ai_service.weights = {}
    ai_service.drawings_at_version = 0
    print("[seed] wiped players, drawings, versions and crowd state")


def run(n_players: int, n_drawings: int, seed: int, do_reset: bool) -> dict:
    init_db()
    load_rounds_catalogue()
    rng = np.random.default_rng(seed)
    pyrng = random.Random(seed)

    with SessionLocal() as db:
        if do_reset:
            reset(db)
        ai_service.load_state(db)

        typed = db.execute(select(Round.id, Round.type).where(Round.active)).all()
        round_ids = [rid for rid, _ in typed]
        if not round_ids:
            raise SystemExit("no rounds — run `python -m pipeline.build_rounds --offline`")

        personas = [Persona(rng, i) for i in range(n_players)]
        players = []
        started = datetime.now(timezone.utc) - timedelta(hours=6)
        for p in personas:
            row = Player(id=uuid.uuid4().hex[:24], name=p.name, is_bot=True,
                         created_at=started, last_seen=started)
            db.add(row)
            players.append(row)
        db.commit()

        # Each simulated player works through a shuffled slice of the catalogue,
        # so popular rounds accumulate a real crowd rather than one drawing each.
        pool = round_ids[:]
        pyrng.shuffle(pool)
        # Rounds the crowd converges on, split evenly across types so every
        # type gets enough crowd-backed rounds to fit its blend weight.
        by_type: dict[str, list[str]] = {}
        for rid, kind in typed:
            by_type.setdefault(kind, []).append(rid)
        per_type = max(30, len(pool) // 4) // max(1, len(by_type))
        hot = []
        for kind in sorted(by_type):
            ids = sorted(by_type[kind])
            pyrng.shuffle(ids)
            hot += ids[:per_type]
        queues = {}
        for row in players:
            picks = pyrng.sample(hot, min(len(hot), 12)) + pyrng.sample(pool, 8)
            pyrng.shuffle(picks)
            queues[row.id] = list(dict.fromkeys(picks))

        made = 0
        retrains = 0
        cursor = 0
        while made < n_drawings:
            progressed = False
            for row, persona in zip(players, personas):
                if made >= n_drawings:
                    break
                queue = queues[row.id]
                if not queue:
                    continue
                round_id = queue.pop()
                progressed = True
                rnd = db.get(Round, round_id)
                if rnd is None:
                    continue
                payload = rnd.payload

                ai_curve, _model, crowd_curve, crowd_n = ai_service.curves(rnd)
                curve = persona.draw(rng, payload)
                breakdown = scoring.score_round(
                    curve, payload["hidden"], visible=payload["visible"],
                    ai_curve=ai_curve, crowd_curve=crowd_curve, crowd_n=crowd_n,
                    streak=row.streak,
                )

                anchor = float(payload["visible"][-1])
                truth = np.asarray(payload["hidden"], dtype=float)
                db.add(Drawing(
                    round_id=round_id, player_id=row.id, curve_json=json.dumps(curve),
                    time_ms=int(rng.integers(2600, 9800)), mode="endless",
                    round_type=rnd.type,
                    base_score=breakdown.base, total_score=breakdown.total,
                    rmse=breakdown.rmse, ai_rmse=breakdown.ai_rmse,
                    crowd_rmse=breakdown.crowd_rmse,
                    beat_ai=any(b.key == "beat_ai" for b in breakdown.bonuses),
                    beat_crowd=any(b.key == "beat_crowd" for b in breakdown.bonuses),
                    bullseye=breakdown.bullseye,
                    signed_error=float(np.mean(np.asarray(curve) - truth)),
                    pred_move=float(curve[-1] - anchor),
                    true_move=float(truth[-1] - anchor),
                    player_round_index=row.rounds_played + 1,
                    created_at=started + timedelta(seconds=cursor * 17),
                ))
                ai_service.update_crowd(rnd, curve)
                row.rounds_played += 1
                row.total_score += breakdown.total
                row.streak = breakdown.streak_after
                row.best_streak = max(row.best_streak, breakdown.streak_after)
                made += 1
                cursor += 1

                if made % config.RETRAIN_EVERY == 0:
                    db.commit()
                    if ai_service.retrain(db, note=f"demo seed · {made} drawings"):
                        retrains += 1
            if not progressed:
                break

        db.commit()
        if retrains == 0 or made % config.RETRAIN_EVERY:
            if ai_service.retrain(db, note="demo seed · final", force=True):
                retrains += 1

        summary = {
            "players": db.scalar(select(func.count(Player.id))),
            "drawings": db.scalar(select(func.count(Drawing.id))),
            "versions": db.scalar(select(func.count(AIVersion.id))),
            "rounds_with_crowd": db.scalar(select(func.count(Round.id)).where(
                Round.crowd_n >= config.MIN_CROWD)),
            "weights": ai_service.weights,
        }
    print(f"[seed] {summary}")
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--players", type=int, default=40)
    ap.add_argument("--drawings", type=int, default=600)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--reset", action="store_true", help="wipe play data first")
    args = ap.parse_args()
    run(args.players, args.drawings, args.seed, args.reset)
