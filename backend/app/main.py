"""TAPE: Draw It — FastAPI backend."""

from __future__ import annotations

import json
import random
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone

import numpy as np
from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import scoring

from . import config
from .ai import ai_service
from .daily import daily_number, pick_daily, share_grid
from .db import SessionLocal, engine, get_session, init_db, load_rounds_catalogue
from .models import AIVersion, Drawing, Player, Round, utcnow
from .schemas import (
    AIVersionOut,
    LeaderRow,
    PlayerIn,
    PlayerOut,
    RoundOut,
    SubmitIn,
    SubmitOut,
    public_round,
)

@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    added, retired = load_rounds_catalogue()
    with SessionLocal() as db:
        ai_service.load_state(db)
        total = db.scalar(select(func.count(Round.id)).where(Round.active)) or 0
    print(f"[api] ready — {total} rounds ({added} new, {retired} retired), "
          f"AI v{ai_service.version}", flush=True)
    yield


app = FastAPI(title="TAPE: Draw It", version="1.0.0", lifespan=lifespan,
              description="Draw the future. Beat the AI. Teach it something.")
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS or ["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- simple in-memory rate limiter ---------------------------------------
_submit_log: dict[str, deque[float]] = defaultdict(deque)


def rate_limit(player_id: str) -> None:
    now = time.monotonic()
    log = _submit_log[player_id]
    while log and now - log[0] > config.SUBMIT_WINDOW_S:
        log.popleft()
    if len(log) >= config.SUBMIT_MAX_PER_WINDOW:
        raise HTTPException(429, "Slow down — too many submissions.")
    log.append(now)


# --- helpers --------------------------------------------------------------
def _get_player(db: Session, player_id: str) -> Player:
    player = db.get(Player, player_id)
    if player is None:
        raise HTTPException(404, "Unknown player — pick a name first.")
    return player


def _ids_by_type(db: Session) -> dict[str, list[str]]:
    """Active rounds only -- a retired round must never be dealt again."""
    out: dict[str, list[str]] = {}
    for rid, kind in db.execute(
            select(Round.id, Round.type).where(Round.active)).all():
        out.setdefault(kind, []).append(rid)
    return out


def _played_ids(db: Session, player_id: str) -> set[str]:
    return set(db.scalars(
        select(Drawing.round_id).where(Drawing.player_id == player_id)).all())


def _round_or_404(db: Session, round_id: str) -> Round:
    rnd = db.get(Round, round_id)
    if rnd is None:
        raise HTTPException(404, "No such round.")
    return rnd


# --- endpoints ------------------------------------------------------------
@app.get("/api/health")
def health(db: Session = Depends(get_session)) -> dict:
    return {
        "ok": True,
        "rounds": db.scalar(select(func.count(Round.id)).where(Round.active)) or 0,
        "rounds_retired": db.scalar(
            select(func.count(Round.id)).where(~Round.active)) or 0,
        "drawings": db.scalar(select(func.count(Drawing.id))) or 0,
        "players": db.scalar(select(func.count(Player.id))) or 0,
        "ai_version": ai_service.version,
        "forecaster_trained": ai_service.bank.is_trained(),
    }


@app.post("/api/player", response_model=PlayerOut)
def upsert_player(body: PlayerIn, db: Session = Depends(get_session)) -> PlayerOut:
    player = db.get(Player, body.player_id) if body.player_id else None
    if player is None:
        player = Player(id=body.player_id or uuid.uuid4().hex[:24], name=body.name)
        db.add(player)
    else:
        player.name = body.name
    player.last_seen = utcnow()
    db.commit()
    return PlayerOut(player_id=player.id, name=player.name,
                     rounds_played=player.rounds_played, total_score=player.total_score,
                     streak=player.streak, best_streak=player.best_streak)


@app.get("/api/daily")
def get_daily(db: Session = Depends(get_session)) -> dict:
    ids = pick_daily(_ids_by_type(db))
    return {"number": daily_number(), "date": date.today().isoformat(),
            "round_ids": ids, "count": len(ids)}


@app.get("/api/round/next", response_model=RoundOut)
def next_round(
    mode: str = Query("endless", pattern="^(daily|endless)$"),
    player_id: str = Query(..., min_length=1, max_length=40),
    db: Session = Depends(get_session),
) -> RoundOut:
    _get_player(db, player_id)
    played = _played_ids(db, player_id)

    if mode == "daily":
        ids = pick_daily(_ids_by_type(db))
        for i, rid in enumerate(ids):
            if rid not in played:
                rnd = db.get(Round, rid)
                if rnd is None or not rnd.active:
                    continue
                return RoundOut(round=public_round(rnd.payload, round_id=rnd.id),
                                mode=mode, index=i + 1, of=len(ids),
                                daily_number=daily_number())
        return RoundOut(round=None, mode=mode, index=len(ids), of=len(ids),
                        done=True, daily_number=daily_number())

    active = [rid for rid, in db.execute(select(Round.id).where(Round.active)).all()]
    pool = [rid for rid in active if rid not in played]
    if not pool:                      # played everything: let them replay
        pool = active
    if not pool:
        raise HTTPException(503, "No rounds loaded — run the data pipeline.")
    rnd = db.get(Round, random.choice(pool))
    return RoundOut(round=public_round(rnd.payload, round_id=rnd.id), mode=mode,
                    index=len(played) + 1, of=0)


@app.post("/api/round/{round_id}/submit", response_model=SubmitOut)
def submit(round_id: str, body: SubmitIn, background: BackgroundTasks,
           db: Session = Depends(get_session)) -> SubmitOut:
    rate_limit(body.player_id)
    player = _get_player(db, body.player_id)
    rnd = _round_or_404(db, round_id)
    payload = rnd.payload
    truth = payload["hidden"]

    if db.scalar(select(func.count(Drawing.id)).where(
            Drawing.round_id == round_id, Drawing.player_id == body.player_id)):
        raise HTTPException(409, "You already played this round.")

    # Crowd/AI curves are computed *before* this drawing joins the crowd, so a
    # player is never compared against a mean that includes their own line.
    ai_curve, model_curve, crowd_curve, crowd_n = ai_service.curves(rnd)

    if body.skipped:
        breakdown = scoring.skipped_round(streak=player.streak)
    else:
        breakdown = scoring.score_round(
            body.curve, truth,
            visible=payload["visible"],
            ai_curve=ai_curve,
            crowd_curve=crowd_curve,
            crowd_n=crowd_n,
            streak=player.streak,
        )

    anchor = float(payload["visible"][-1])
    drawing = Drawing(
        round_id=round_id, player_id=player.id, curve_json=json.dumps(body.curve),
        time_ms=body.time_ms, mode=body.mode, round_type=rnd.type, is_fake=rnd.is_fake,
        base_score=breakdown.base, total_score=breakdown.total, rmse=breakdown.rmse,
        ai_rmse=breakdown.ai_rmse, crowd_rmse=breakdown.crowd_rmse,
        beat_ai=any(b.key == "beat_ai" for b in breakdown.bonuses),
        beat_crowd=any(b.key == "beat_crowd" for b in breakdown.bonuses),
        bullseye=breakdown.bullseye,
        signed_error=float(np.mean(np.asarray(body.curve) - np.asarray(truth))),
        pred_move=float(body.curve[-1] - anchor),
        true_move=float(truth[-1] - anchor),
        player_round_index=player.rounds_played + 1,
    )
    db.add(drawing)

    if not body.skipped:
        ai_service.update_crowd(rnd, body.curve)
    player.rounds_played += 1
    player.total_score += breakdown.total
    player.streak = breakdown.streak_after
    player.best_streak = max(player.best_streak, breakdown.streak_after)
    player.last_seen = utcnow()

    try:
        db.commit()
    except IntegrityError:            # racing double-submit
        db.rollback()
        raise HTTPException(409, "You already played this round.") from None

    total_drawings = db.scalar(select(func.count(Drawing.id))) or 0
    if ai_service.should_retrain(total_drawings):
        background.add_task(_retrain_task)

    return SubmitOut(
        round_id=round_id,
        truth=truth,
        ai_curve=ai_curve,
        crowd_curve=crowd_curve,
        crowd_n=crowd_n,
        score_breakdown=breakdown.to_dict(),
        reveal_info=payload.get("reveal_info", {}),
        is_fake=bool(rnd.is_fake),
        streak=breakdown.streak_after,
        ai_version=ai_service.version,
        player_total=player.total_score,
    )


def _retrain_task(note: str = "", force: bool = False) -> None:
    """Runs off the request path so a submit never waits on model fitting."""
    with SessionLocal() as db:
        ai_service.retrain(db, note=note, force=force)


@app.get("/api/ai/version", response_model=AIVersionOut)
def ai_version(db: Session = Depends(get_session)) -> AIVersionOut:
    row = db.scalars(select(AIVersion).order_by(AIVersion.version.desc())).first()
    if row is None:
        return AIVersionOut(version=0, created_at=None, drawings_seen=0,
                            new_drawings=0, weights={}, rmse_model=None,
                            rmse_crowd=None, rmse_blend=None, n_eval=0,
                            note="model only — no crowd data yet")
    return AIVersionOut(
        version=row.version,
        created_at=row.created_at.isoformat() if row.created_at else None,
        drawings_seen=row.drawings_seen, new_drawings=row.new_drawings,
        weights=row.weights, rmse_model=row.rmse_model, rmse_crowd=row.rmse_crowd,
        rmse_blend=row.rmse_blend, n_eval=row.n_eval, note=row.note)


@app.post("/api/admin/retrain")
def admin_retrain(background: BackgroundTasks,
                  x_admin_token: str = Header(default="")) -> dict:
    """Force a retrain mid-pitch. Guarded by TAPE_ADMIN_TOKEN."""
    if x_admin_token != config.ADMIN_TOKEN:
        raise HTTPException(401, "Bad admin token.")
    background.add_task(_retrain_task, "forced from the demo shortcut", True)
    return {"queued": True, "current_version": ai_service.version}


@app.get("/api/leaderboard")
def leaderboard(period: str = Query("all", pattern="^(today|all)$"),
                limit: int = Query(25, ge=1, le=100),
                db: Session = Depends(get_session)) -> dict:
    if period == "today":
        since = datetime.combine(date.today(), datetime.min.time(), timezone.utc)
        rows = db.execute(
            select(Player.id, Player.name, Player.is_bot,
                   func.sum(Drawing.total_score), func.count(Drawing.id),
                   func.max(Drawing.base_score))
            .join(Drawing, Drawing.player_id == Player.id)
            .where(Drawing.created_at >= since)
            .group_by(Player.id)
            .order_by(func.sum(Drawing.total_score).desc())
            .limit(limit)).all()
        out = [LeaderRow(rank=i + 1, player_id=pid, name=name, score=int(score or 0),
                         rounds=int(n or 0), best_streak=0,
                         avg=round(float(score or 0) / max(int(n or 1), 1), 1),
                         is_bot=bool(bot))
               for i, (pid, name, bot, score, n, _best) in enumerate(rows)]
    else:
        rows = db.scalars(
            select(Player).where(Player.rounds_played > 0)
            .order_by(Player.total_score.desc()).limit(limit)).all()
        out = [LeaderRow(rank=i + 1, player_id=p.id, name=p.name,
                         score=p.total_score, rounds=p.rounds_played,
                         best_streak=p.best_streak,
                         avg=round(p.total_score / max(p.rounds_played, 1), 1),
                         is_bot=p.is_bot)
               for i, p in enumerate(rows)]
    return {"period": period, "rows": [r.model_dump() for r in out]}


@app.get("/api/player/{player_id}/daily")
def player_daily(player_id: str, db: Session = Depends(get_session)) -> dict:
    """The player's Daily 5 result so far, plus the share string."""
    _get_player(db, player_id)
    ids = pick_daily(_ids_by_type(db))
    rows = {d.round_id: d for d in db.scalars(
        select(Drawing).where(Drawing.player_id == player_id,
                              Drawing.round_id.in_(ids))).all()}
    scores = [rows[i].base_score for i in ids if i in rows]
    beat_ai = sum(1 for i in ids if i in rows and rows[i].beat_ai)
    return {
        "number": daily_number(),
        "complete": len(scores) == len(ids) and bool(ids),
        "scores": scores,
        "beat_ai": beat_ai,
        "total": sum(rows[i].total_score for i in ids if i in rows),
        "share": share_grid(scores, beat_ai) if scores else "",
    }


@app.get("/api/dashboard")
def dashboard(db: Session = Depends(get_session)) -> dict:
    # 1. AI version history.
    versions = db.scalars(select(AIVersion).order_by(AIVersion.version)).all()
    history = [{
        "version": v.version,
        "created_at": v.created_at.isoformat() if v.created_at else None,
        "drawings_seen": v.drawings_seen,
        "model": v.rmse_model, "crowd": v.rmse_crowd, "blend": v.rmse_blend,
        "n_eval": v.n_eval, "weights": v.weights, "note": v.note,
    } for v in versions]

    # 2. Player improvement by round number, bucketed in fives.
    # Floor division, not `/`: SQLAlchemy renders `/` as float division, which
    # would put rounds 1 and 2 in different buckets (0.0 vs 0.2).
    bucket_expr = ((Drawing.player_round_index - 1) // 5).label("bucket")
    buckets = db.execute(
        select(bucket_expr, func.avg(Drawing.base_score), func.count(Drawing.id))
        .group_by(bucket_expr).order_by(bucket_expr)).all()
    improvement = [{
        "bucket": f"{int(b) * 5 + 1}–{int(b) * 5 + 5}",
        "avg_score": round(float(avg or 0), 1), "n": int(n or 0),
    } for b, avg, n in buckets if n]

    # 3. Human bias: signed error per type (>0 means drawn above the truth).
    bias = [{
        "type": kind,
        "avg_signed_error": round(float(avg or 0), 5),
        "avg_abs_error": round(float(rms or 0), 5),
        "n": int(n or 0),
    } for kind, avg, rms, n in db.execute(
        select(Drawing.round_type, func.avg(Drawing.signed_error),
               func.avg(Drawing.rmse), func.count(Drawing.id))
        .group_by(Drawing.round_type).order_by(Drawing.round_type)).all()]

    # 3b. Fake vs real headline reaction, the disinformation finding.
    headline = []
    for label, is_fake in (("real headline", False), ("fake headline", True)):
        row = db.execute(
            select(func.avg(Drawing.pred_move), func.avg(Drawing.true_move),
                   func.avg(Drawing.base_score), func.count(Drawing.id))
            .where(Drawing.round_type.in_(["stock", "fake_stock"]),
                   Drawing.is_fake == is_fake)).first()
        pred, true, score, n = row or (0, 0, 0, 0)
        headline.append({
            "label": label,
            "avg_predicted_move": round(float(pred or 0), 5),
            "avg_actual_move": round(float(true or 0), 5),
            "overreaction": round(float(pred or 0) - float(true or 0), 5),
            "avg_score": round(float(score or 0), 1),
            "n": int(n or 0),
        })

    # 4. Totals.
    beat_ai = db.scalar(select(func.count(Drawing.id)).where(Drawing.beat_ai)) or 0
    drawings = db.scalar(select(func.count(Drawing.id))) or 0
    latest = versions[-1] if versions else None
    totals = {
        "drawings": drawings,
        "players": db.scalar(select(func.count(Player.id))) or 0,
        "rounds": db.scalar(select(func.count(Round.id)).where(Round.active)) or 0,
        "ai_version": ai_service.version,
        "beat_ai_rate": round(beat_ai / drawings, 4) if drawings else 0.0,
        "avg_score": round(float(db.scalar(select(func.avg(Drawing.base_score))) or 0), 1),
        "bullseyes": db.scalar(select(func.count(Drawing.id)).where(Drawing.bullseye)) or 0,
        "weights": ai_service.weights,
        "rounds_with_crowd": db.scalar(select(func.count(Round.id)).where(
            Round.crowd_n >= config.MIN_CROWD)) or 0,
        "retrain_every": config.RETRAIN_EVERY,
        "next_retrain_in": max(0, config.RETRAIN_EVERY -
                               (drawings - ai_service.drawings_at_version)),
        "latest_note": latest.note if latest else "",
    }
    return {"versions": history, "improvement": improvement, "bias": bias,
            "headline_bias": headline, "totals": totals}
