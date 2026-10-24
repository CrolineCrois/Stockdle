"""Request/response models, and the one function that keeps the answer secret."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from . import config

# Fields of a round record that must never reach the client before submit.
SECRET_FIELDS = ("hidden", "feat", "span")


def public_round(payload: dict, *, round_id: str | None = None) -> dict:
    """Strip the answer out of a round record.

    This is the single choke point for round serialisation. ``hidden`` is the
    truth, ``feat`` leaks the forecast high / headline age the truth depends on,
    and ``span`` would let someone look the window up in the source file.
    """
    out = {k: v for k, v in payload.items() if k not in SECRET_FIELDS}
    out["id"] = round_id or payload.get("id")
    out.pop("reveal_info", None)       # that is the post-submit payload
    return out


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


class PlayerOut(BaseModel):
    player_id: str
    name: str
    rounds_played: int
    total_score: int
    streak: int
    best_streak: int


class SubmitIn(BaseModel):
    player_id: str = Field(min_length=1, max_length=40)
    curve: list[float]
    time_ms: int = Field(ge=0, le=600_000)
    mode: Literal["daily", "endless"] = "endless"
    skipped: bool = False

    @field_validator("curve")
    @classmethod
    def check_curve(cls, v: list[float]) -> list[float]:
        if len(v) != config.CURVE_LEN:
            raise ValueError(f"curve must have exactly {config.CURVE_LEN} points")
        out = []
        for x in v:
            if not isinstance(x, (int, float)) or x != x or x in (float("inf"), float("-inf")):
                raise ValueError("curve must contain finite numbers")
            out.append(min(1.0, max(0.0, float(x))))
        return out


class SubmitOut(BaseModel):
    round_id: str
    truth: list[float]
    ai_curve: list[float]
    crowd_curve: list[float] | None
    crowd_n: int
    score_breakdown: dict[str, Any]
    reveal_info: dict[str, Any]
    streak: int
    ai_version: int
    player_total: int


class RoundOut(BaseModel):
    round: dict[str, Any] | None
    mode: str
    index: int = 0
    of: int = 0
    done: bool = False
    daily_number: int | None = None


class LeaderRow(BaseModel):
    rank: int
    name: str
    player_id: str
    score: int
    rounds: int
    best_streak: int
    avg: float
    is_bot: bool = False


class AIVersionOut(BaseModel):
    version: int
    created_at: str | None
    drawings_seen: int
    new_drawings: int
    weights: dict[str, float]
    rmse_model: float | None
    rmse_crowd: float | None
    rmse_blend: float | None
    n_eval: int
    note: str
