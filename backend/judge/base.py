"""The verdict every judge returns, and the interface they share."""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, Field

EDIT_TYPES = ("number change", "negation", "entity swap", "causal claim", "other")
EditType = Literal["number change", "negation", "entity swap", "causal claim", "other"]


class Verdict(BaseModel):
    is_false: bool = Field(description="The edited headline makes a claim the article does not support or contradicts.")
    is_plausible: bool = Field(description="A reader could believe it at a glance.")
    is_grammatical: bool
    edit_type: EditType
    explanation: str = Field(max_length=600)

    @property
    def valid_lie(self) -> bool:
        """A lie worth scoring: false, believable and well formed."""
        return self.is_false and self.is_plausible and self.is_grammatical


class JudgeUnavailable(RuntimeError):
    """The judge could not give a verdict (network, rate limit, bad output).

    The game treats this as "attempt not counted": no attempt is used, no
    time is lost, and the player can resubmit.
    """


class Judge(Protocol):
    name: str

    def judge(self, original: str, snippet: str, edited: str) -> Verdict: ...
