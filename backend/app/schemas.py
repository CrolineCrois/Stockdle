"""Request bodies and the shapes the client reads."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from . import config, game
from .models import Headline, Player, Round, Run


class PlayerIn(BaseModel):
    name: str = Field(min_length=1, max_length=32)
    player_id: str | None = Field(default=None, max_length=40)

    @field_validator("name")
    @classmethod
    def clean_name(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("name cannot be blank")
        return v[:32]


class PlayerRef(BaseModel):
    player_id: str = Field(min_length=1, max_length=40)


class EditIn(PlayerRef):
    edited: str = Field(min_length=1, max_length=300)


class TracePoint(BaseModel):
    t_ms: int = Field(ge=0, le=600_000)       # ms since the round started
    s: float = Field(ge=0.0, le=1.0)          # meter value shown
    text: str | None = Field(default=None, max_length=300)


class SubmitIn(EditIn):
    trace: list[TracePoint] = Field(default_factory=list, max_length=600)
    time_to_submit_ms: int = Field(default=0, ge=0, le=600_000)


class TimeoutIn(PlayerRef):
    edited: str = Field(default="", max_length=300)
    trace: list[TracePoint] = Field(default_factory=list, max_length=600)
    time_to_submit_ms: int = Field(default=0, ge=0, le=600_000)


def player_out(p: Player) -> dict:
    return {"player_id": p.id, "name": p.name, "runs": p.runs, "best_score": p.best_score}


def run_out(run: Run) -> dict:
    return {"id": run.id, "lives": run.lives, "max_lives": config.LIVES,
            "streak": run.streak, "best_streak": run.best_streak, "score": run.score,
            "snuck": run.snuck, "caught": run.caught, "rounds_played": run.rounds_played,
            "over": run.ended_at is not None, "detector_version": run.detector_version}


def round_out(rnd: Round, headline: Headline) -> dict:
    return {
        "id": rnd.id, "status": rnd.status, "is_bounty": rnd.is_bounty,
        "timer_start_s": rnd.timer_start_s,
        "remaining_s": round(max(0.0, game.remaining_s(rnd)), 3),
        "attempts_used": rnd.attempts_used, "max_attempts": config.MAX_ATTEMPTS,
        "headline": {
            "id": headline.id, "text": headline.text, "snippet": headline.snippet,
            "source": headline.source, "url": headline.url,
            "published_at": headline.published_at.isoformat() + "Z"
            if headline.published_at else None,
        },
    }


def rules_out() -> dict:
    return {"max_words": config.MAX_WORD_CHANGES, "threshold": config.SNEAK_THRESHOLD,
            "near_miss_from": config.NEAR_MISS_FROM, "max_attempts": config.MAX_ATTEMPTS,
            "lives": config.LIVES}
