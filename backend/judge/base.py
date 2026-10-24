"""The verdict every judge returns, the two-run ruling, and the shared interface.

A *verdict* is one judge run. A *ruling* combines two runs made with different
prompt phrasings: both must say the edit is false, or the edit is invalid.
The ruling then applies the anti-loophole rules:

    materiality < 3                                   -> invalid: "Too pedantic"
    specificity drops by >= 2 vs the original,
      or any vagueness flag                           -> "Too vague"
        ... and if specificity <= 2                   -> counts as CAUGHT
        ... otherwise                                 -> points x 0.5
    specificity kept equal to the original and >= 4  -> "Sharp lie" x1.5
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Literal, Protocol

from pydantic import BaseModel, Field

EDIT_TYPES = ("number", "role swap", "causal", "temporal", "negation", "quantifier",
              "entity swap", "other")
EditType = Literal["number", "role swap", "causal", "temporal", "negation", "quantifier",
                   "entity swap", "other"]
PHRASINGS = ("a", "b")

MIN_MATERIALITY = 3
VAGUE_DROP = 2
VAGUE_CAUGHT_AT = 2
SHARP_AT = 4


class Verdict(BaseModel):
    is_false: bool = Field(description="A reader would come away believing something the source contradicts.")
    is_grammatical: bool
    is_plausible: bool = Field(description="A reader could believe it at a glance.")
    materiality: int = Field(ge=1, le=5)
    specificity: int = Field(ge=1, le=5, description="Of the edited headline.")
    original_specificity: int = Field(ge=1, le=5, description="Of the original headline, same scale.")
    vagueness_flags: list[str] = Field(default_factory=list, max_length=10)
    edit_type: EditType
    explanation: str = Field(max_length=800)


@dataclass
class Ruling:
    """Two judge runs combined into one decision about the edit."""

    runs: list[dict]
    valid: bool                    # a lie worth sending to the verifier
    reason: str                    # why not, when invalid; "" otherwise
    materiality: int
    specificity: int
    original_specificity: int
    vagueness_flags: list[str] = field(default_factory=list)
    edit_type: str = "other"
    explanation: str = ""
    vague: bool = False
    vague_caught: bool = False     # too vague to count: treated as CAUGHT
    sharp: bool = False

    def tags(self) -> list[str]:
        out = []
        if self.reason == "pedantic":
            out.append("Too pedantic")
        if self.vague:
            out.append("Too vague — caught" if self.vague_caught else "Too vague −50%")
        if self.sharp:
            out.append("Sharp lie ×1.5")
        return out

    def to_dict(self) -> dict:
        return {"runs": self.runs, "valid": self.valid, "reason": self.reason,
                "materiality": self.materiality, "specificity": self.specificity,
                "original_specificity": self.original_specificity,
                "vagueness_flags": self.vagueness_flags, "edit_type": self.edit_type,
                "explanation": self.explanation, "vague": self.vague,
                "vague_caught": self.vague_caught, "sharp": self.sharp, "tags": self.tags()}


def rule(a: Verdict, b: Verdict, *, judge: str, model: str | None) -> Ruling:
    """Combine two runs. Conservative throughout: the stricter reading wins."""
    runs = [{**a.model_dump(), "phrasing": "a"}, {**b.model_dump(), "phrasing": "b"}]
    for r in runs:
        r.update(judge=judge, model=model)
    mat = min(a.materiality, b.materiality)
    spec = min(a.specificity, b.specificity)
    orig = max(a.original_specificity, b.original_specificity)
    flags = sorted(set(a.vagueness_flags) | set(b.vagueness_flags))
    base = dict(runs=runs, materiality=mat, specificity=spec, original_specificity=orig,
                vagueness_flags=flags, edit_type=a.edit_type, explanation=a.explanation)

    if a.is_false != b.is_false:
        return Ruling(valid=False, reason="disagree",
                      **{**base, "explanation": "The two judges disagreed about whether "
                                                "this is false, so it doesn't count."})
    if not a.is_false:
        return Ruling(valid=False, reason="not_false", **base)
    if not (a.is_plausible and b.is_plausible):
        return Ruling(valid=False, reason="implausible", **base)
    if not (a.is_grammatical and b.is_grammatical):
        return Ruling(valid=False, reason="ungrammatical", **base)
    if mat < MIN_MATERIALITY:
        return Ruling(valid=False, reason="pedantic", **base)

    vague = bool(flags) or (orig - spec >= VAGUE_DROP)
    return Ruling(valid=True, reason="", vague=vague,
                  vague_caught=vague and spec <= VAGUE_CAUGHT_AT,
                  sharp=not vague and spec == orig and spec >= SHARP_AT, **base)


class JudgeUnavailable(RuntimeError):
    """The judge could not give a verdict (network, rate limit, bad output).

    The game treats this as "attempt not counted": no attempt is used, no
    time is lost, and the player can resubmit.
    """


class Judge(Protocol):
    name: str

    def judge(self, original: str, snippet: str, edited: str, phrasing: str = "a") -> Verdict: ...


def judge_twice(judge: Judge, original: str, snippet: str, edited: str) -> Ruling:
    """Both phrasings, in parallel (the player's clock is paused while we wait)."""
    with ThreadPoolExecutor(max_workers=2) as pool:
        fa = pool.submit(judge.judge, original, snippet, edited, "a")
        fb = pool.submit(judge.judge, original, snippet, edited, "b")
        a, b = fa.result(), fb.result()
    return rule(a, b, judge=judge.name, model=getattr(judge, "model", None))
