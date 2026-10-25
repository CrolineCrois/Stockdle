"""Erm, Akthually 🤓 — FastAPI backend.

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
    GET  /api/analytics                 everything on the /lab dashboard
    GET  /api/verifier/versions         evidence-verifier versions and which is live
    GET  /api/learning                  per-version benchmark + live catch rates (How it learns)
    GET  /api/admin/review              exploit review queue + counters (x-admin-token)
    POST /api/admin/review/{id}         approve / reject an exploit (x-admin-token)
    GET  /api/health                    status, current detector, judge in use
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from detector import registry
from verifier import registry as verifiers
from judge import get_judge

from . import analytics, config, game, review
from .db import get_session, init_db
from .diffing import word_diff
from .models import Attempt, Headline, Player, Round, Run, utcnow
from .schemas import (
    EditIn,
    PlayerIn,
    PlayerRef,
    RunIn,
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
        from verifier import registry as verifiers
        from verifier.retrieval import retrieve
        verifiers.current().score("warm up", ["warm up"])      # and the verifier, not on first submit
        retrieve("warm up")
    except LookupError:
        det = "none (run `python -m detector.train_stub`)"
    print(f"[api] ready — detector {det}, judge {get_judge().name}", flush=True)
    yield


app = FastAPI(title="Erm, Akthually", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS or ["*"],
                   allow_origin_regex=config.CORS_ORIGIN_REGEX or None,
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


_windows: dict[str, deque[float]] = defaultdict(deque)


def _limit(key: str, limit: int, per_s: float, message: str) -> None:
    """Sliding-window rate limit (in memory: one server process)."""
    now, log = time.monotonic(), _windows[key]
    while log and now - log[0] > per_s:
        log.popleft()
    if limit > 0 and len(log) >= limit:
        raise HTTPException(429, message)
    log.append(now)


def _ip(request: Request) -> str:
    # Behind a Cloudflare tunnel every request comes from localhost; the real
    # client is in CF-Connecting-IP.
    return (request.headers.get("cf-connecting-ip")
            or request.headers.get("x-forwarded-for", "").split(",")[0].strip()
            or (request.client.host if request.client else "?"))


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
def upsert_player(body: PlayerIn, request: Request, db: Session = Depends(get_session)) -> dict:
    p = db.get(Player, body.player_id) if body.player_id else None
    if p is None:
        _limit(f"player:{_ip(request)}", config.PLAYERS_PER_IP_PER_HOUR, 3600,
               "Too many new players from this network — try again later.")
        p = Player(id=body.player_id or uuid.uuid4().hex[:24], name=body.name)
        db.add(p)
    else:
        p.name = body.name
    p.last_seen = utcnow()
    db.commit()
    return player_out(p)


@app.post("/api/run")
def start_run(body: RunIn, db: Session = Depends(get_session)) -> dict:
    player = _player(db, body.player_id)
    run, _ = _game_errors(lambda: game.start_run(db, player, body.level))
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
    rnd, run, headline = _round(db, round_id, player)
    diff = word_diff(headline.text, body.edited)
    return {
        "suspicion": game.suspicion(headline, body.edited, game.level_of(run)),
        "num_changes": diff.num_changes,
        "changes": diff.changed_words,
        "over_limit": diff.num_changes > config.MAX_WORD_CHANGES,
        "remaining_s": round(max(0.0, game.remaining_s(rnd)), 3),
    }


def _evidence_out(db: Session, ver) -> list[dict]:
    """The passages the verifier used, as short attributed excerpts for the reveal."""
    if ver is None:
        return []
    out = []
    for e in ver.passages:
        h = db.get(Headline, e.headline_id)
        text = e.text if len(e.text) <= 420 else e.text[:420].rsplit(" ", 1)[0] + "…"
        out.append({"text": text, "source": h.source if h else "", "url": h.url if h else "",
                    "headline": h.text if h else "", "probs": e.probs, "decisive": e.decisive})
    return out


def _result_out(db: Session, res: game.Result, run: Run) -> dict:
    a = res.attempt
    ver = res.verification
    return {
        "outcome": res.outcome,
        "suspicion": a.suspicion_score_final,
        "mode": a.mode,
        "tags": res.tags,
        "verifier": None if ver is None else {
            "verdict": ver.verdict, "probs": ver.probs, "version": ver.version,
            "evidence": _evidence_out(db, ver)},
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
def submit(round_id: str, body: SubmitIn, request: Request, db: Session = Depends(get_session)) -> dict:
    _limit(f"submit:{_ip(request)}", config.SUBMITS_PER_IP_PER_MIN, 60,
           "Slow down — too many submissions from this network.")
    _limit("submit:all", config.SUBMITS_PER_HOUR, 3600,
           "The judge is at its hourly limit — try again in a few minutes.")
    player = _player(db, body.player_id)
    rnd, run, _ = _round(db, round_id, player)
    res = _game_errors(lambda: game.submit(
        db, player=player, rnd=rnd, edited=body.edited, auto=body.auto,
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


@app.get("/api/levels")
def levels(db: Session = Depends(get_session)) -> dict:
    """Every fact-checker version as a playable level, easiest first."""
    from app.learning import live_by_verifier
    live = {x["version"]: x["caught"] for x in live_by_verifier(db)}
    rows, newest = verifiers.levels(), verifiers.newest_level()
    out = []
    for i, v in enumerate(rows):
        bench = json.loads(v.metrics_json or "{}").get("benchmark") or {}
        out.append({"name": v.name, "number": i, "newest": v.name == newest,
                    "n_train": v.n_train, "note": v.note,
                    "created_at": v.created_at.isoformat() + "Z",
                    "points_mult": game.level_mult(v.name),
                    "held_out_caught": bench.get("human_lies_caught"),
                    "live_caught": live.get(v.name)})
    return {"levels": out, "newest": newest}


@app.get("/api/leaderboard")
def leaderboard(db: Session = Depends(get_session)) -> dict:
    rows = db.execute(
        select(Run, Player.name).join(Player, Player.id == Run.player_id)
        .where(Run.score > 0).order_by(Run.score.desc()).limit(25)).all()
    return {"rows": [{"rank": i + 1, "name": name, "score": r.score, "snuck": r.snuck,
                      "best_streak": r.best_streak, "detector_version": r.detector_version,
                      "level": game.level_of(r)}
                     for i, (r, name) in enumerate(rows)]}


FAKE_LABEL = "FAKE — made in Erm, Akthually"


@app.get("/api/exploits")
def exploit_board(limit: int = 20, db: Session = Depends(get_session)) -> dict:
    """The Exploit Board: novel tricks that got past the detector.

    These are player-made fakes, so every one carries ``label`` and the client
    must show it beside the text. There is deliberately no feed, export or
    share path for them outside the game.
    """
    limit = max(1, min(limit, 50))
    newest = verifiers.newest_level()
    # Exploits against the newest fact-checker first; older levels still listed.
    rows = db.execute(
        select(Attempt, Player.name).join(Player, Player.id == Attempt.player_id)
        .where(Attempt.outcome == "snuck", Attempt.is_novel)
        .order_by((Attempt.verifier_version == newest).desc(), Attempt.points.desc())
        .limit(limit)).all()
    return {"label": FAKE_LABEL, "rows": [{
        "id": a.id, "player": name, "original": a.original_headline,
        "edited": a.edited_headline, "label": FAKE_LABEL, "edit_type": a.edit_type,
        "changes": a.changed_words, "points": a.points,
        "suspicion": a.suspicion_score_final, "novelty_distance": a.novelty_distance,
        "detector_version": a.detector_version, "patched_in": a.patched_in,
        "level": a.verifier_version or "v0", "newest": (a.verifier_version or "v0") == newest,
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
def trigger_patch_day(x_admin_token: str | None = Header(default=None)) -> dict:
    """Run a verifier patch day in the background (for a live demo). Token-guarded."""
    if x_admin_token != config.ADMIN_TOKEN:
        raise HTTPException(401, "bad admin token")
    if not _patch_lock.acquire(blocking=False):
        raise HTTPException(409, "a patch day is already running")

    def work():
        from verifier import patch_day
        _patch_status["running"] = True
        try:
            _patch_status["last"] = patch_day.run()
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


@app.get("/api/analytics")
def get_analytics(judge: str = "all", db: Session = Depends(get_session)) -> dict:
    """Everything on /lab. ``judge=real`` drops mock-judged attempts."""
    if judge not in ("all", "real"):
        raise HTTPException(422, "judge must be 'all' or 'real'")
    return analytics.build(db, judge)


def _admin(token: str | None) -> None:
    if token != config.ADMIN_TOKEN:
        raise HTTPException(401, "bad admin token")


@app.get("/api/admin/review")
def review_queue(status: str = "pending", limit: int = 50,
                 x_admin_token: str | None = Header(default=None),
                 db: Session = Depends(get_session)) -> dict:
    """Exploits waiting for (or past) human review. Admin only: contains fakes."""
    _admin(x_admin_token)
    if status not in ("pending", "approved", "rejected", "all"):
        raise HTTPException(422, "bad status")
    return {"label": FAKE_LABEL, "items": review.queue(db, status, max(1, min(limit, 200))),
            "stats": review.stats(db)}


class ReviewIn(BaseModel):
    decision: str = Field(pattern="^(approved|rejected)$")
    reviewer: str = Field(min_length=1, max_length=40)
    note: str = Field(default="", max_length=300)


@app.post("/api/admin/review/{attempt_id}")
def review_decide(attempt_id: int, body: ReviewIn,
                  x_admin_token: str | None = Header(default=None),
                  db: Session = Depends(get_session)) -> dict:
    _admin(x_admin_token)
    try:
        a = review.decide(db, attempt_id, body.decision, body.reviewer, body.note)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"id": a.id, "review_status": a.review_status, "stats": review.stats(db)}


@app.get("/api/verifier/versions")
def verifier_versions() -> dict:
    """Every evidence-verifier version: what it trained on, and which is live."""
    from verifier import registry as verifiers
    current = verifiers.current_name()
    return {"current": current, "versions": [{
        "name": v.name, "created_at": v.created_at.isoformat() + "Z", "train_data": v.train_data,
        "n_train": v.n_train, "note": v.note, "is_current": v.name == current,
        "metrics": json.loads(v.metrics_json or "{}"),
    } for v in verifiers.versions()]}


@app.get("/api/learning")
def learning_summary() -> dict:
    """The How-it-learns scorecard: benchmark per version, plus live catch rates."""
    from . import learning
    return learning.summary()
