"""Sneak It Past — FastAPI backend.

    POST /api/player                    create or rename a player
    POST /api/run                       start a run (3 lives) and its first round
    GET  /api/run/{run_id}              current run state
    POST /api/run/{run_id}/next         deal the next headline
    POST /api/round/{id}/suspicion      live meter: P(false) for the current edit
    POST /api/round/{id}/submit         judge + score one attempt
    POST /api/round/{id}/timeout        the clock ran out
    GET  /api/leaderboard               best runs
    GET  /api/exploits                  the Exploit Board (labelled fakes)
    GET  /api/player/{id}/notices       "your exploit was patched"
    GET  /api/detector/versions         every detector version and its metrics
    POST /api/admin/patch-day           run a patch day (x-admin-token)
    GET  /api/health                    status, current detector, judge in use
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException
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
        registry.current().predict([("warm up", "warm up")])   # load weights now, not on first keystroke
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


FAKE_LABEL = "FAKE — made in Sneak It Past"


@app.get("/api/exploits")
def exploit_board(limit: int = 20, db: Session = Depends(get_session)) -> dict:
    """The Exploit Board: novel tricks that got past the detector.

    These are player-made fakes, so every one carries ``label`` and the client
    must show it beside the text. There is deliberately no feed, export or
    share path for them outside the game.
    """
    limit = max(1, min(limit, 50))
    rows = db.execute(
        select(Attempt, Player.name).join(Player, Player.id == Attempt.player_id)
        .where(Attempt.outcome == "snuck", Attempt.is_novel)
        .order_by(Attempt.points.desc()).limit(limit)).all()
    return {"label": FAKE_LABEL, "rows": [{
        "id": a.id, "player": name, "original": a.original_headline,
        "edited": a.edited_headline, "label": FAKE_LABEL, "edit_type": a.edit_type,
        "changes": a.changed_words, "points": a.points,
        "suspicion": a.suspicion_score_final, "novelty_distance": a.novelty_distance,
        "detector_version": a.detector_version, "patched_in": a.patched_in,
        "created_at": a.created_at.isoformat() + "Z",
    } for a, name in rows]}


@app.get("/api/player/{player_id}/notices")
def notices(player_id: str, db: Session = Depends(get_session)) -> dict:
    """Exploits of yours that a patch day has since caught. Each is shown once."""
    rows = db.scalars(select(Attempt).where(
        Attempt.player_id == player_id, Attempt.outcome == "snuck",
        Attempt.patched_in.is_not(None), ~Attempt.patch_notified)).all()
    out = [{"id": a.id, "patched_in": a.patched_in, "original": a.original_headline,
            "changes": a.changed_words, "label": FAKE_LABEL} for a in rows]
    for a in rows:
        a.patch_notified = True
    db.commit()
    return {"notices": out}


@app.get("/api/detector/versions")
def detector_versions() -> dict:
    current = registry.current_name()
    return {"current": current, "versions": [{
        "name": v.name, "kind": v.kind, "created_at": v.created_at.isoformat() + "Z",
        "n_train": v.n_train, "metrics": json.loads(v.metrics_json or "{}"), "note": v.note,
        "is_current": v.name == current,
    } for v in registry.versions()]}


_patch_lock = threading.Lock()
_patch_status: dict = {"running": False, "last": None}


@app.post("/api/admin/patch-day")
def trigger_patch_day(include_mock: bool = False,
                      x_admin_token: str | None = Header(default=None)) -> dict:
    """Run a patch day in the background (for a live demo). Token-guarded."""
    if x_admin_token != config.ADMIN_TOKEN:
        raise HTTPException(401, "bad admin token")
    if not _patch_lock.acquire(blocking=False):
        raise HTTPException(409, "a patch day is already running")

    def work():
        from detector import patch_day
        _patch_status["running"] = True
        try:
            _patch_status["last"] = patch_day.run(include_mock=include_mock)
        except Exception as exc:  # noqa: BLE001 - report it rather than kill the thread silently
            _patch_status["last"] = {"shipped": False, "reason": f"{type(exc).__name__}: {exc}"}
        finally:
            _patch_status["running"] = False
            _patch_lock.release()

    threading.Thread(target=work, daemon=True).start()
    return {"started": True}


@app.get("/api/admin/patch-day")
def patch_day_status() -> dict:
    return _patch_status
