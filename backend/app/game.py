"""Game rules: runs, rounds, the timer, attempts and outcomes.

The server owns the clock. A round's remaining time is

    timer_start - (now - started_at - paused)

where ``paused`` is time spent waiting on the judge, so API latency never
costs the player. A submission arriving up to ``TIMER_GRACE_S`` after zero
still counts (network slack); later than that it is a timeout.

Outcomes of one submission:

    invalid   the judge says it is not false / not plausible / not grammatical.
              No life lost; the attempt is used. A third invalid attempt ends
              the round as "exhausted": no life lost, but the streak resets.
    snuck     judged false AND suspicion < 0.5: points, streak + 1.
    caught    judged false AND suspicion >= 0.5: lose a life, streak resets.
    timeout   the clock ran out first: counts as caught.
"""

from __future__ import annotations

import json
import random
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from detector import registry
from detector.base import predict_one
from judge import JudgeUnavailable, get_judge

from . import config, novelty, scoring
from .diffing import word_diff
from .models import Attempt, Headline, Player, Round, Run, utcnow


class GameError(Exception):
    """A rule violation the client should show to the player (HTTP 400/409)."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


# --- clock -----------------------------------------------------------------
def remaining_s(rnd: Round, now: datetime | None = None) -> float:
    now = now or utcnow()
    elapsed = (now - rnd.started_at).total_seconds() - rnd.paused_s
    return rnd.timer_start_s - elapsed


# --- runs and rounds -------------------------------------------------------
def start_run(db: Session, player: Player) -> tuple[Run, Round]:
    for old in db.scalars(select(Run).where(Run.player_id == player.id,
                                            Run.ended_at.is_(None))).all():
        old.ended_at = utcnow()                      # abandon any unfinished run
    run = Run(id=uuid.uuid4().hex[:20], player_id=player.id, lives=config.LIVES,
              detector_version=registry.current_name())
    db.add(run)
    player.runs += 1
    db.flush()
    rnd = next_round(db, run)
    return run, rnd


def next_round(db: Session, run: Run) -> Round:
    if run.ended_at is not None or run.lives <= 0:
        raise GameError("This run is over.", 409)
    active = db.scalar(select(Round).where(Round.run_id == run.id, Round.status == "active"))
    if active is not None:
        return active                               # idempotent: one live round at a time

    seen = set(db.scalars(select(Round.headline_id).where(Round.run_id == run.id)).all())
    pool = db.scalars(select(Headline.id).where(Headline.active)).all()
    choices = [h for h in pool if h not in seen] or list(pool)
    if not choices:
        raise GameError("No headlines loaded yet.", 503)
    headline = db.get(Headline, random.choice(choices))
    rnd = Round(id=uuid.uuid4().hex[:20], run_id=run.id, headline_id=headline.id,
                is_bounty=headline.is_bounty,
                timer_start_s=scoring.timer_seconds(run.streak, headline.is_bounty))
    db.add(rnd)
    db.flush()
    return rnd


def suspicion(headline: Headline, edited: str) -> float:
    return round(predict_one(registry.current(), edited, headline.snippet), 4)


# --- submissions -----------------------------------------------------------
@dataclass
class Result:
    attempt: Attempt
    outcome: str
    points: scoring.Points | None
    verdict: dict
    near_miss: bool
    round_over: bool
    run_over: bool
    remaining_s: float
    events: list[str] = field(default_factory=list)


def _end_round(db: Session, run: Run, rnd: Round, status: str) -> None:
    rnd.status, rnd.ended_at = status, utcnow()
    run.rounds_played += 1


def _end_run_if_dead(db: Session, run: Run, player: Player) -> bool:
    if run.lives > 0:
        return False
    run.ended_at = utcnow()
    player.best_score = max(player.best_score, run.score)
    return True


def _log(db: Session, *, rnd: Round, run: Run, player: Player, headline: Headline,
         edited: str, diff, susp: float | None, trace: list, verdict: dict, outcome: str,
         points: int, remaining: float, time_to_submit_ms: int, timed_out: bool) -> Attempt:
    att = Attempt(
        round_id=rnd.id, run_id=run.id, player_id=player.id, attempt_no=rnd.attempts_used,
        headline_id=headline.id, original_headline=headline.text, edited_headline=edited,
        changed_words_json=json.dumps(diff.changed_words if diff else []),
        num_words_changed=diff.num_changes if diff else 0,
        suspicion_score_final=susp, suspicion_trace_json=json.dumps(trace[-400:]),
        judge_output_json=json.dumps(verdict), edit_type=verdict.get("edit_type", ""),
        outcome=outcome, points=points, streak=run.streak, lives_left=run.lives,
        detector_version=registry.current_name(), is_bounty=rnd.is_bounty,
        time_to_submit_ms=time_to_submit_ms, timer_start_seconds=rnd.timer_start_s,
        time_remaining_at_submit=round(max(0.0, remaining), 3), timed_out=timed_out,
    )
    db.add(att)
    db.flush()
    return att


def _timeout(db: Session, run: Run, rnd: Round, player: Player, headline: Headline,
             edited: str, trace: list, time_to_submit_ms: int) -> Result:
    run.lives -= 1
    run.caught += 1
    run.streak = 0
    rnd.attempts_used += 1
    att = _log(db, rnd=rnd, run=run, player=player, headline=headline, edited=edited,
               diff=word_diff(headline.text, edited), susp=None, trace=trace,
               verdict={}, outcome="timeout", points=0, remaining=0.0,
               time_to_submit_ms=time_to_submit_ms, timed_out=True)
    _end_round(db, run, rnd, "timeout")
    over = _end_run_if_dead(db, run, player)
    return Result(att, "timeout", None, {}, False, True, over, 0.0, ["times_up"])


def submit(db: Session, *, player: Player, rnd: Round, edited: str, trace: list,
           time_to_submit_ms: int) -> Result:
    run = db.get(Run, rnd.run_id)
    if run.player_id != player.id:
        raise GameError("That round belongs to someone else.", 403)
    if rnd.status != "active" or run.ended_at is not None:
        raise GameError("That round is already over.", 409)
    headline = db.get(Headline, rnd.headline_id)
    edited = " ".join(edited.split())

    if remaining_s(rnd) < -config.TIMER_GRACE_S:
        return _timeout(db, run, rnd, player, headline, edited, trace, time_to_submit_ms)

    diff = word_diff(headline.text, edited)
    if diff.num_changes == 0:
        raise GameError("Change at least one word.")
    if diff.num_changes > config.MAX_WORD_CHANGES:
        raise GameError(f"That's {diff.num_changes} word changes; the limit is "
                        f"{config.MAX_WORD_CHANGES}.")

    susp = suspicion(headline, edited)          # server-side: never trust the client's meter
    remaining = remaining_s(rnd)                # frozen now; the judge's time is not counted

    judge = get_judge()
    t0 = time.monotonic()
    try:
        verdict_obj = judge.judge(headline.text, headline.snippet, edited)
    except JudgeUnavailable as exc:
        rnd.paused_s += time.monotonic() - t0   # refund the wait; no attempt used
        db.commit()
        raise GameError(f"The judge is unavailable ({exc}). Your clock was paused; "
                        "try again.", 503) from exc
    rnd.paused_s += time.monotonic() - t0
    verdict = {**verdict_obj.model_dump(), "judge": judge.name,
               "model": getattr(judge, "model", None)}

    rnd.attempts_used += 1
    events: list[str] = []
    points: scoring.Points | None = None
    embedding, novelty_distance, is_novel = None, None, False

    if not verdict_obj.valid_lie:
        outcome = "invalid"
        round_over = rnd.attempts_used >= config.MAX_ATTEMPTS
        if round_over:
            run.streak = 0
            _end_round(db, run, rnd, "exhausted")
            events.append("exhausted")
    elif susp < config.SNEAK_THRESHOLD:
        outcome = "snuck"
        embedding, novelty_distance, is_novel = novelty.assess(
            db, headline.text, edited, diff.changed_words)
        points = scoring.sneak_points(suspicion=susp, num_words=diff.num_changes,
                                      streak=run.streak, remaining_s=max(0.0, remaining),
                                      start_s=rnd.timer_start_s, is_novel=is_novel,
                                      is_bounty=rnd.is_bounty)
        if is_novel:
            events.append("zero_day")
        run.score += points.total
        run.snuck += 1
        run.streak += 1
        run.best_streak = max(run.best_streak, run.streak)
        _end_round(db, run, rnd, "snuck")
        round_over = True
        events.append("snuck")
        if points.quick_hands:
            events.append("quick_hands")
    else:
        outcome = "caught"
        run.lives -= 1
        run.caught += 1
        run.streak = 0
        _end_round(db, run, rnd, "caught")
        round_over = True
        events.append("caught")

    # Suspicion in [0.4, 0.5) is still under the line: snuck past, but only just.
    near = outcome == "snuck" and scoring.is_near_miss(susp)
    if near:
        events.append("near_miss")
    att = _log(db, rnd=rnd, run=run, player=player, headline=headline, edited=edited,
               diff=diff, susp=susp, trace=trace, verdict=verdict, outcome=outcome,
               points=points.total if points else 0, remaining=remaining,
               time_to_submit_ms=time_to_submit_ms, timed_out=False)
    att.novelty_distance, att.is_novel = novelty_distance, is_novel
    att.edit_embedding_json = json.dumps(embedding) if embedding else ""
    run_over = _end_run_if_dead(db, run, player)
    return Result(att, outcome, points, verdict, near, round_over, run_over,
                  max(0.0, remaining_s(rnd)), events)


def report_timeout(db: Session, *, player: Player, rnd: Round, edited: str, trace: list,
                   time_to_submit_ms: int) -> Result:
    """The client's clock hit zero. Accepted only if the server's clock agrees."""
    run = db.get(Run, rnd.run_id)
    if run.player_id != player.id:
        raise GameError("That round belongs to someone else.", 403)
    if rnd.status != "active":
        raise GameError("That round is already over.", 409)
    if remaining_s(rnd) > config.TIMER_GRACE_S:
        raise GameError("There is still time on the clock.", 409)
    headline = db.get(Headline, rnd.headline_id)
    return _timeout(db, run, rnd, player, headline, " ".join(edited.split()), trace,
                    time_to_submit_ms)
