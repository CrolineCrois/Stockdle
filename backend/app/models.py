"""SQLite schema: players, rounds, drawings, ai_versions."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Player(Base):
    __tablename__ = "players"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    rounds_played: Mapped[int] = mapped_column(Integer, default=0)
    total_score: Mapped[int] = mapped_column(Integer, default=0)
    best_streak: Mapped[int] = mapped_column(Integer, default=0)
    streak: Mapped[int] = mapped_column(Integer, default=0)
    is_bot: Mapped[bool] = mapped_column(Boolean, default=False)

    drawings: Mapped[list["Drawing"]] = relationship(back_populates="player")


class Round(Base):
    """One playable round. ``payload`` holds the full record incl. ``hidden``.

    The API never serialises ``payload`` directly -- see ``schemas.public_round``
    -- so the answer cannot leak before submit.
    """

    __tablename__ = "rounds"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    type: Mapped[str] = mapped_column(String(20), index=True)
    source_key: Mapped[str] = mapped_column(String(40))
    is_fake: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_seed: Mapped[bool] = mapped_column(Boolean, default=True)
    payload_json: Mapped[str] = mapped_column(Text)
    crowd_sum_json: Mapped[str] = mapped_column(Text, default="")
    crowd_n: Mapped[int] = mapped_column(Integer, default=0)
    play_count: Mapped[int] = mapped_column(Integer, default=0)
    # False once a pipeline rebuild drops this round from the catalogue.
    # Retired rounds are never dealt again, but are kept so the drawings and
    # leaderboard scores that reference them stay intact.
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    @property
    def payload(self) -> dict:
        return json.loads(self.payload_json)

    @property
    def crowd_sum(self) -> list[float] | None:
        if not self.crowd_sum_json:
            return None
        return json.loads(self.crowd_sum_json)

    @property
    def crowd_mean(self) -> list[float] | None:
        total = self.crowd_sum
        if not total or self.crowd_n <= 0:
            return None
        return [v / self.crowd_n for v in total]


class Drawing(Base):
    __tablename__ = "drawings"
    __table_args__ = (
        # Rate limit: one scored drawing per player per round.
        UniqueConstraint("round_id", "player_id", name="uq_drawing_round_player"),
        Index("ix_drawings_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    round_id: Mapped[str] = mapped_column(ForeignKey("rounds.id"), index=True)
    player_id: Mapped[str] = mapped_column(ForeignKey("players.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)

    curve_json: Mapped[str] = mapped_column(Text)
    time_ms: Mapped[int] = mapped_column(Integer, default=0)
    mode: Mapped[str] = mapped_column(String(10), default="endless")
    round_type: Mapped[str] = mapped_column(String(20), index=True)
    is_fake: Mapped[bool] = mapped_column(Boolean, default=False)

    base_score: Mapped[int] = mapped_column(Integer, default=0)
    total_score: Mapped[int] = mapped_column(Integer, default=0)
    rmse: Mapped[float] = mapped_column(Float, default=0.0)
    ai_rmse: Mapped[float | None] = mapped_column(Float, nullable=True)
    crowd_rmse: Mapped[float | None] = mapped_column(Float, nullable=True)
    beat_ai: Mapped[bool] = mapped_column(Boolean, default=False)
    beat_crowd: Mapped[bool] = mapped_column(Boolean, default=False)
    bullseye: Mapped[bool] = mapped_column(Boolean, default=False)

    # Bias analytics (see /api/dashboard).
    signed_error: Mapped[float] = mapped_column(Float, default=0.0)
    pred_move: Mapped[float] = mapped_column(Float, default=0.0)
    true_move: Mapped[float] = mapped_column(Float, default=0.0)
    player_round_index: Mapped[int] = mapped_column(Integer, default=1, index=True)

    player: Mapped[Player] = relationship(back_populates="drawings")

    @property
    def curve(self) -> list[float]:
        return json.loads(self.curve_json)


class AIVersion(Base):
    __tablename__ = "ai_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    drawings_seen: Mapped[int] = mapped_column(Integer, default=0)
    new_drawings: Mapped[int] = mapped_column(Integer, default=0)
    weights_json: Mapped[str] = mapped_column(Text, default="{}")
    rmse_model: Mapped[float | None] = mapped_column(Float, nullable=True)
    rmse_crowd: Mapped[float | None] = mapped_column(Float, nullable=True)
    rmse_blend: Mapped[float | None] = mapped_column(Float, nullable=True)
    n_eval: Mapped[int] = mapped_column(Integer, default=0)
    base_refit: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str] = mapped_column(String(200), default="")

    @property
    def weights(self) -> dict[str, float]:
        try:
            return json.loads(self.weights_json)
        except Exception:  # noqa: BLE001
            return {}
