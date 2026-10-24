"""Game rules: runs, rounds, the timer, attempts and outcomes.

The server owns the clock. A round's remaining time is

    timer_start - (now - started_at - paused)

where ``paused`` is time spent waiting on the judge and the verifier, so API
and model latency never cost the player. A submission arriving up to
``TIMER_GRACE_S`` after zero still counts (network slack); later than that it
is a timeout.

One submission:

    1. The judge runs twice (two phrasings). Invalid -- no life lost, the try is
       used -- if they disagree, if it isn't false / plausible / grammatical, or
       if materiality < 3 ("Too pedantic"). A third invalid try ends the round
       as "exhausted": no life lost, but the streak resets.
    2. Too vague with specificity <= 2 counts as CAUGHT outright.
    3. Otherwise the evidence verifier decides:
         SUPPORTED  -> snuck    full points, streak + 1   ("Misread evidence!")
         NOT ENOUGH -> partial  0.3x points, streak held (doesn't grow)
         REFUTED    -> caught   lose a life, streak resets
    When the clock runs out, whatever is in the box is auto-submitted and judged
    as usual -- if it's a legal edit (1-3 word changes). An illegal edit, or an
    auto-submitted one the judge rules not a lie (no clock left to retry), is a
    timeout, which counts as caught.

The style model's suspicion is computed and logged for the live meter only;
it never decides an outcome.
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
from judge import JudgeUnavailable, get_judge, judge_twice
from verifier.verify import BREAKING, EVIDENCE, Verification, verify

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
                mode=BREAKING if headline.is_bounty else EVIDENCE,
                timer_start_s=scoring.timer_seconds(run.streak, headline.is_bounty))
    db.add(rnd)
    db.flush()
    return rnd


def suspicion(headline: Headline, edited: str) -> float:
    """The "first glance" score for the live meter: a small fast model reading the
    edit against the source passage the verifier is most likely to use."""
    from detector.premise import premise_for
    return round(predict_one(registry.current(), edited, premise_for(headline.id)), 4)


# --- submissions -----------------------------------------------------------
@dataclass
class Result:
    attempt: Attempt
    outcome: str
    points: scoring.Points | None
    verdict: dict
    verification: Verification | None
    tags: list[str]
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
         points: int, remaining: float, time_to_submit_ms: int, timed_out: bool,
         verification: Verification | None = None, tags: list[str] | None = None) -> Attempt:
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
        mode=rnd.mode, tags_json=json.dumps(tags or []),
        materiality=verdict.get("materiality"), specificity=verdict.get("specificity"),
        original_specificity=verdict.get("original_specificity"),
        vagueness_flags_json=json.dumps(verdict.get("vagueness_flags", [])),
        # Lies that got through (fully or partly) wait for human review.
        review_status="pending" if outcome in ("snuck", "partial") else "",
    )
    if verification is not None:
        att.verifier_version = verification.version
        att.verifier_verdict = verification.verdict
        att.verifier_probs_json = json.dumps(verification.probs)
        att.retrieved_passage_ids_json = json.dumps(verification.passage_ids)
    db.add(att)
    db.flush()
    return att


def _timeout(db: Session, run: Run, rnd: Round, player: Player, headline: Headline,
             edited: str, trace: list, time_to_submit_ms: int, verdict: dict | None = None) -> Result:
    run.lives -= 1
    run.caught += 1
    run.streak = 0
    rnd.attempts_used += 1
    att = _log(db, rnd=rnd, run=run, player=player, headline=headline, edited=edited,
               diff=word_diff(headline.text, edited), susp=None, trace=trace,
               verdict=verdict or {}, outcome="timeout", points=0, remaining=0.0,
               time_to_submit_ms=time_to_submit_ms, timed_out=True)
    _end_round(db, run, rnd, "timeout")
    over = _end_run_if_dead(db, run, player)
    return Result(att, "timeout", None, verdict or {}, None, [], False, True, over, 0.0, ["times_up"])


def submit(db: Session, *, player: Player, rnd: Round, edited: str, trace: list,
           time_to_submit_ms: int, auto: bool = False) -> Result:
    run = db.get(Run, rnd.run_id)
    if run.player_id != player.id:
        raise GameError("That round belongs to someone else.", 403)
    if rnd.status != "active" or run.ended_at is not None:
        raise GameError("That round is already over.", 409)
    headline = db.get(Headline, rnd.headline_id)
    edited = " ".join(edited.split())

    if remaining_s(rnd) < -config.TIMER_GRACE_S:
        return _timeout(db, run, rnd, player, headline, edited, trace, time_to_submit_ms)

    # An exact repeat of an edit the judge already ruled not-a-lie this round:
    # answer from that ruling instead of burning a try (and a judge call) on it.
    prior = db.scalar(select(Attempt).where(Attempt.round_id == rnd.id, Attempt.outcome == "invalid",
                                            Attempt.edited_headline == edited)
                      .order_by(Attempt.id.desc()))
    if prior is not None:
        ruling_was = json.loads(prior.judge_output_json or "{}")
        if not auto:
            raise GameError(f"You already tried that exact edit — "
                            f"{ruling_was.get('explanation') or 'the judge said it is not a lie.'} "
                            "Change something before resubmitting.", 409)
        return _timeout(db, run, rnd, player, headline, edited, trace, time_to_submit_ms,
                        verdict=ruling_was)

    diff = word_diff(headline.text, edited)
    if auto and not 1 <= diff.num_changes <= config.MAX_WORD_CHANGES:
        # Out of time with nothing legal to submit.
        return _timeout(db, run, rnd, player, headline, edited, trace, time_to_submit_ms)
    if diff.num_changes == 0:
        raise GameError("Change at least one word.")
    if diff.num_changes > config.MAX_WORD_CHANGES:
        raise GameError(f"That's {diff.num_changes} word changes; the limit is "
                        f"{config.MAX_WORD_CHANGES}.")

    susp = suspicion(headline, edited)          # server-side: never trust the client's meter
    remaining = remaining_s(rnd)                # frozen now; judge + verifier time not counted

    judge = get_judge()
    t0 = time.monotonic()
    try:
        ruling = judge_twice(judge, headline.text, headline.snippet, edited)
    except JudgeUnavailable as exc:
        rnd.paused_s += time.monotonic() - t0   # refund the wait; no attempt used
        db.commit()
        raise GameError(f"The judge is unavailable ({exc}). Your clock was paused; "
                        "try again.", 503) from exc
    verdict = ruling.to_dict()
    verdict["judge"] = judge.name
    verdict["model"] = getattr(judge, "model", None)

    verification = None
    if ruling.valid and not ruling.vague_caught:
        verification = verify(edited, headline.id, rnd.mode)
    rnd.paused_s += time.monotonic() - t0

    rnd.attempts_used += 1
    events: list[str] = []
    tags = ruling.tags()
    points: scoring.Points | None = None
    embedding, novelty_distance, is_novel = None, None, False

    if auto:
        tags.insert(0, "Time's up — auto-submitted")
    if not ruling.valid and auto:
        # Not a lie, and no clock left to try again: the round ends as a timeout.
        outcome = "timeout"
        run.lives -= 1
        run.caught += 1
        run.streak = 0
        _end_round(db, run, rnd, "timeout")
        round_over = True
        events.append("times_up")
    elif not ruling.valid:
        outcome = "invalid"
        round_over = rnd.attempts_used >= config.MAX_ATTEMPTS
        if round_over:
            run.streak = 0
            _end_round(db, run, rnd, "exhausted")
            events.append("exhausted")
    elif ruling.vague_caught or verification.verdict == "refuted":
        outcome = "caught"
        run.lives -= 1
        run.caught += 1
        run.streak = 0
        _end_round(db, run, rnd, "caught")
        round_over = True
        events.append("caught")
    else:
        outcome = "snuck" if verification.verdict == "supported" else "partial"
        if outcome == "snuck":
            embedding, novelty_distance, is_novel = novelty.assess(
                db, headline.text, edited, diff.changed_words)
            if is_novel:
                events.append("zero_day")
            if rnd.mode == EVIDENCE:
                tags.append("Misread evidence!")
        else:
            tags.append("Not enough info ×0.3")
        points = scoring.sneak_points(
            suspicion=verification.probs.get("refuted", 0.0), num_words=diff.num_changes,
            streak=run.streak, remaining_s=max(0.0, remaining), start_s=rnd.timer_start_s,
            is_novel=is_novel, is_bounty=rnd.is_bounty, materiality=ruling.materiality,
            sharp=ruling.sharp, vague=ruling.vague, partial=outcome == "partial")
        run.score += points.total
        if outcome == "snuck":
            run.snuck += 1
            run.streak += 1                       # partial holds the streak, doesn't grow it
            run.best_streak = max(run.best_streak, run.streak)
        else:
            run.partial += 1
        _end_round(db, run, rnd, outcome)
        round_over = True
        events.append(outcome)
        if points.quick_hands:
            events.append("quick_hands")

    # Verifier's P(refuted) in [0.4, 0.5) on a sneak: under the line, but only just.
    near = outcome == "snuck" and scoring.is_near_miss(verification.probs.get("refuted", 0.0))
    if near:
        events.append("near_miss")
    att = _log(db, rnd=rnd, run=run, player=player, headline=headline, edited=edited,
               diff=diff, susp=susp, trace=trace, verdict=verdict, outcome=outcome,
               points=points.total if points else 0, remaining=remaining,
               time_to_submit_ms=time_to_submit_ms, timed_out=auto,
               verification=verification, tags=tags)
    att.novelty_distance, att.is_novel = novelty_distance, is_novel
    att.edit_embedding_json = json.dumps(embedding) if embedding else ""
    run_over = _end_run_if_dead(db, run, player)
    return Result(att, outcome, points, verdict, verification, tags, near, round_over,
                  run_over, max(0.0, remaining_s(rnd)), events)


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
