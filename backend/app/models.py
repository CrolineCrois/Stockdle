"""SQLite schema.

    headlines          the pool of real, true headlines (+ article snippet)
    players            display name only, no accounts
    runs               one game: 3 lives, a streak, a score
    rounds             one headline inside a run: its timer and attempt count
    attempts           EVERY submission, valid or not -- the research log
    detector_versions  each trained detector, so versions can be compared
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    # Naive UTC: SQLite has no timezone type, so store everything as UTC.
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Headline(Base):
    __tablename__ = "headlines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    text: Mapped[str] = mapped_column(String(300))
    # Normalised text, unique: the dedup key across feeds and re-scrapes.
    norm: Mapped[str] = mapped_column(String(300), unique=True, index=True)
    snippet: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(80), default="")
    url: Mapped[str] = mapped_column(String(500), default="")
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    scraped_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    is_seed: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    # Bounties: the headlines the current detector is most suspicious of
    # *before* any edit -- sneaking a lie past it there is genuinely hard.
    is_bounty: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    detector_p: Mapped[float | None] = mapped_column(Float, nullable=True)


class Player(Base):
    __tablename__ = "players"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    best_score: Mapped[int] = mapped_column(Integer, default=0)
    runs: Mapped[int] = mapped_column(Integer, default=0)
    is_bot: Mapped[bool] = mapped_column(Boolean, default=False)


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    player_id: Mapped[str] = mapped_column(ForeignKey("players.id"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    lives: Mapped[int] = mapped_column(Integer)
    streak: Mapped[int] = mapped_column(Integer, default=0)
    best_streak: Mapped[int] = mapped_column(Integer, default=0)
    score: Mapped[int] = mapped_column(Integer, default=0)
    snuck: Mapped[int] = mapped_column(Integer, default=0)
    caught: Mapped[int] = mapped_column(Integer, default=0)
    rounds_played: Mapped[int] = mapped_column(Integer, default=0)
    detector_version: Mapped[str] = mapped_column(String(20), default="")


class Round(Base):
    """One headline inside a run. The timer lives here, server-side.

    ``paused_s`` accumulates time spent waiting on the judge, which never
    counts against the player.
    """

    __tablename__ = "rounds"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    headline_id: Mapped[int] = mapped_column(ForeignKey("headlines.id"))
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    timer_start_s: Mapped[float] = mapped_column(Float)
    paused_s: Mapped[float] = mapped_column(Float, default=0.0)
    attempts_used: Mapped[int] = mapped_column(Integer, default=0)
    is_bounty: Mapped[bool] = mapped_column(Boolean, default=False)
    # active -> snuck | caught | timeout | exhausted (3 invalid attempts)
    status: Mapped[str] = mapped_column(String(12), default="active")


class Attempt(Base):
    """Every submission, logged in full. This table *is* the dataset."""

    __tablename__ = "attempts"
    __table_args__ = (Index("ix_attempts_outcome_created", "outcome", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    round_id: Mapped[str] = mapped_column(ForeignKey("rounds.id"), index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    player_id: Mapped[str] = mapped_column(ForeignKey("players.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    attempt_no: Mapped[int] = mapped_column(Integer)

    headline_id: Mapped[int] = mapped_column(ForeignKey("headlines.id"), index=True)
    original_headline: Mapped[str] = mapped_column(String(300))
    edited_headline: Mapped[str] = mapped_column(String(400))
    changed_words_json: Mapped[str] = mapped_column(Text, default="[]")
    num_words_changed: Mapped[int] = mapped_column(Integer, default=0)

    suspicion_score_final: Mapped[float | None] = mapped_column(Float, nullable=True)
    suspicion_trace_json: Mapped[str] = mapped_column(Text, default="[]")
    judge_output_json: Mapped[str] = mapped_column(Text, default="{}")
    edit_type: Mapped[str] = mapped_column(String(30), default="")

    # snuck | caught | invalid | timeout
    outcome: Mapped[str] = mapped_column(String(10), index=True)
    points: Mapped[int] = mapped_column(Integer, default=0)
    streak: Mapped[int] = mapped_column(Integer, default=0)      # after this attempt
    lives_left: Mapped[int] = mapped_column(Integer, default=0)
    detector_version: Mapped[str] = mapped_column(String(20), index=True)
    novelty_distance: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_novel: Mapped[bool] = mapped_column(Boolean, default=False)
    is_bounty: Mapped[bool] = mapped_column(Boolean, default=False)
    time_to_submit_ms: Mapped[int] = mapped_column(Integer, default=0)

    timer_start_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    time_remaining_at_submit: Mapped[float] = mapped_column(Float, default=0.0)
    timed_out: Mapped[bool] = mapped_column(Boolean, default=False)

    # Set by a later patch day once a newer detector catches this exploit.
    patched_in: Mapped[str | None] = mapped_column(String(20), nullable=True)

    @property
    def changed_words(self) -> list[dict]:
        return json.loads(self.changed_words_json)

    @property
    def judge_output(self) -> dict:
        return json.loads(self.judge_output_json)


class DetectorVersion(Base):
    __tablename__ = "detector_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(20), unique=True)    # "stub", "v0", "v1"...
    kind: Mapped[str] = mapped_column(String(20))                 # "baseline" | "distilbert"
    path: Mapped[str] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    is_current: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    n_train: Mapped[int] = mapped_column(Integer, default=0)
    metrics_json: Mapped[str] = mapped_column(Text, default="{}")
    note: Mapped[str] = mapped_column(String(300), default="")
