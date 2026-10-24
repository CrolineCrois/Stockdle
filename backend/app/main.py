"""Sneak It Past — FastAPI backend.

    POST /api/player                    create or rename a player
    POST /api/run                       start a run (3 lives) and its first round
    GET  /api/run/{run_id}              current run state
    POST /api/run/{run_id}/next         deal the next headline
    POST /api/round/{id}/suspicion      live meter: P(false) for the current edit
    POST /api/round/{id}/submit         judge + score one attempt
    POST /api/round/{id}/timeout        the clock ran out
    GET  /api/leaderboard               best runs
    GET  /api/health                    status, current detector, judge in use
"""

from __future__ import annotations

import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from detector import registry
from judge import get_judge

from . import config, game
from .db import get_session, init_db
from .diffing import word_diff
from .models import Attempt, Headline, Player, Round, Run, utcnow
from .schemas import (
    EditIn,
    PlayerIn,
    PlayerRef,
    SubmitIn,
    TimeoutIn,
    player_out,
    round_out,
    rules_out,
    run_out,
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    try:
        det = registry.current_name()
    except LookupError:
        det = "none (run `python -m detector.train_stub`)"
    print(f"[api] ready — detector {det}, judge {get_judge().name}", flush=True)
    yield


app = FastAPI(title="Sneak It Past", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS or ["*"],
                   allow_credentials=False, allow_methods=["*"], allow_headers=["*"])


# --- helpers ----------------------------------------------------------------
_meter_calls: dict[str, deque[float]] = defaultdict(deque)


def _meter_rate_limit(player_id: str) -> None:
    now, log = time.monotonic(), _meter_calls[player_id]
    while log and now - log[0] > 1.0:
        log.popleft()
    if len(log) >= config.SUSPICION_RATE_PER_S:
        raise HTTPException(429, "Meter is updating too fast.")
    log.append(now)


def _player(db: Session, player_id: str) -> Player:
    p = db.get(Player, player_id)
    if p is None:
        raise HTTPException(404, "Unknown player — pick a name first.")
    p.last_seen = utcnow()
    return p


def _round(db: Session, round_id: str, player: Player) -> tuple[Round, Run, Headline]:
    rnd = db.get(Round, round_id)
    if rnd is None:
        raise HTTPException(404, "No such round.")
    run = db.get(Run, rnd.run_id)
    if run.player_id != player.id:
        raise HTTPException(403, "That round belongs to someone else.")
    return rnd, run, db.get(Headline, rnd.headline_id)


def _state(db: Session, run: Run) -> dict:
    rnd = db.scalar(select(Round).where(Round.run_id == run.id)
                    .order_by(Round.started_at.desc()))
    return {"run": run_out(run),
            "round": round_out(rnd, db.get(Headline, rnd.headline_id)) if rnd else None,
            "rules": rules_out()}


def _game_errors(fn):
    try:
        return fn()
    except game.GameError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


# --- routes -----------------------------------------------------------------
@app.get("/api/health")
def health(db: Session = Depends(get_session)) -> dict:
    try:
        det = registry.current_name()
    except LookupError:
        det = None
    return {"ok": True, "detector": det, "judge": get_judge().name,
            "headlines": db.scalar(select(func.count(Headline.id)).where(Headline.active)) or 0,
            "attempts": db.scalar(select(func.count(Attempt.id))) or 0}


@app.post("/api/player")
def upsert_player(body: PlayerIn, db: Session = Depends(get_session)) -> dict:
    p = db.get(Player, body.player_id) if body.player_id else None
    if p is None:
        p = Player(id=body.player_id or uuid.uuid4().hex[:24], name=body.name)
        db.add(p)
    else:
        p.name = body.name
    p.last_seen = utcnow()
    db.commit()
    return player_out(p)


@app.post("/api/run")
def start_run(body: PlayerRef, db: Session = Depends(get_session)) -> dict:
    player = _player(db, body.player_id)
    run, _ = _game_errors(lambda: game.start_run(db, player))
    db.commit()
    return _state(db, run)


@app.get("/api/run/{run_id}")
def get_run(run_id: str, player_id: str, db: Session = Depends(get_session)) -> dict:
    run = db.get(Run, run_id)
    if run is None or run.player_id != player_id:
        raise HTTPException(404, "No such run.")
    return _state(db, run)


@app.post("/api/run/{run_id}/next")
def next_round(run_id: str, body: PlayerRef, db: Session = Depends(get_session)) -> dict:
    run = db.get(Run, run_id)
    if run is None or run.player_id != body.player_id:
        raise HTTPException(404, "No such run.")
    _game_errors(lambda: game.next_round(db, run))
    db.commit()
    return _state(db, run)


@app.post("/api/round/{round_id}/suspicion")
def live_suspicion(round_id: str, body: EditIn, db: Session = Depends(get_session)) -> dict:
    """The live meter. Cheap by design: detector only, no judge, nothing logged."""
    _meter_rate_limit(body.player_id)
    player = _player(db, body.player_id)
    rnd, _, headline = _round(db, round_id, player)
    diff = word_diff(headline.text, body.edited)
    return {
        "suspicion": game.suspicion(headline, body.edited),
        "num_changes": diff.num_changes,
        "changes": diff.changed_words,
        "over_limit": diff.num_changes > config.MAX_WORD_CHANGES,
        "remaining_s": round(max(0.0, game.remaining_s(rnd)), 3),
    }


def _result_out(db: Session, res: game.Result, run: Run) -> dict:
    a = res.attempt
    return {
        "outcome": res.outcome,
        "suspicion": a.suspicion_score_final,
        "points": res.points.to_dict() if res.points else None,
        "verdict": res.verdict,
        "changes": a.changed_words,
        "num_changes": a.num_words_changed,
        "near_miss": res.near_miss,
        "events": res.events,
        "round_over": res.round_over,
        "run_over": res.run_over,
        "attempts_used": db.get(Round, a.round_id).attempts_used,
        "remaining_s": round(res.remaining_s, 3),
        "state": _state(db, run),
    }


@app.post("/api/round/{round_id}/submit")
def submit(round_id: str, body: SubmitIn, db: Session = Depends(get_session)) -> dict:
    player = _player(db, body.player_id)
    rnd, run, _ = _round(db, round_id, player)
    res = _game_errors(lambda: game.submit(
        db, player=player, rnd=rnd, edited=body.edited,
        trace=[t.model_dump() for t in body.trace], time_to_submit_ms=body.time_to_submit_ms))
    db.commit()
    return _result_out(db, res, run)


@app.post("/api/round/{round_id}/timeout")
def timeout(round_id: str, body: TimeoutIn, db: Session = Depends(get_session)) -> dict:
    player = _player(db, body.player_id)
    rnd, run, _ = _round(db, round_id, player)
    res = _game_errors(lambda: game.report_timeout(
        db, player=player, rnd=rnd, edited=body.edited,
        trace=[t.model_dump() for t in body.trace], time_to_submit_ms=body.time_to_submit_ms))
    db.commit()
    return _result_out(db, res, run)


@app.get("/api/leaderboard")
def leaderboard(db: Session = Depends(get_session)) -> dict:
    rows = db.execute(
        select(Run, Player.name).join(Player, Player.id == Run.player_id)
        .where(Run.score > 0).order_by(Run.score.desc()).limit(25)).all()
    return {"rows": [{"rank": i + 1, "name": name, "score": r.score, "snuck": r.snuck,
                      "best_streak": r.best_streak, "detector_version": r.detector_version}
                     for i, (r, name) in enumerate(rows)]}
