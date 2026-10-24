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


REASON_TEXT = {
    "disagree": "Too close to call — the two judges split on whether that's false, so it doesn't count.",
    "not_false": "Still true — that edit doesn't change a checkable fact.",
    "implausible": "Nobody would believe that{detail}.",
    "ungrammatical": "That doesn't read as a real headline — check the grammar.",
    "pedantic": "Too pedantic — that barely changes what the headline says.",
    "vague": "Too vague — it swaps something checkable for something fuzzy.",
}


def reason_line(reason: str, added: str = "") -> str:
    """The game's own one-line reason, so it can never contradict the ruling."""
    # Name the word only when there is a single change; with several, the
    # combined words mislead (e.g. a harmless "highlights -> highlight" next to
    # the nonsense), so say "that wording" and let the judge's note point.
    detail = ""
    if reason == "implausible":
        detail = (f" — “{added}” doesn't make sense here" if added and "\n" not in added
                  else " — that wording doesn't make sense here")
    return REASON_TEXT[reason].format(detail=detail)


def rule(a: Verdict, b: Verdict, *, judge: str, model: str | None, added: str = "") -> Ruling:
    """Combine two runs.

    Whether the edit is FALSE must be agreed by both runs (the spec's rule). For
    plausibility and grammar a split vote is borderline, so the edit only fails
    if BOTH runs flag it. Materiality and specificity take the stricter reading.
    The explanation shown is from the run whose concern decided the outcome.
    """
    runs = [{**a.model_dump(), "phrasing": "a"}, {**b.model_dump(), "phrasing": "b"}]
    for r in runs:
        r.update(judge=judge, model=model)
    mat = min(a.materiality, b.materiality)
    spec = min(a.specificity, b.specificity)
    orig = max(a.original_specificity, b.original_specificity)
    flags = sorted(set(a.vagueness_flags) | set(b.vagueness_flags))
    base = dict(runs=runs, materiality=mat, specificity=spec, original_specificity=orig,
                vagueness_flags=flags, edit_type=a.edit_type)

    def invalid(reason: str, by: Verdict) -> Ruling:
        return Ruling(valid=False, reason=reason,
                      explanation=f"{reason_line(reason, added)} Judge’s note: {by.explanation}", **base)

    if a.is_false != b.is_false:
        return invalid("disagree", a if not a.is_false else b)
    if not a.is_false:
        return invalid("not_false", a)
    if not (a.is_plausible or b.is_plausible):
        return invalid("implausible", a)
    if not (a.is_grammatical or b.is_grammatical):
        return invalid("ungrammatical", a)
    if mat < MIN_MATERIALITY:
        return invalid("pedantic", a if a.materiality <= b.materiality else b)

    # Vague = a vagueness flag, or specificity dropping by >= 2 against the SAME
    # run's rating of the original. Like grammar, a split vote is borderline:
    # it only counts as vague if BOTH runs say so.
    def vague_in(v: Verdict) -> bool:
        return bool(v.vagueness_flags) or (v.original_specificity - v.specificity >= VAGUE_DROP)

    vague = vague_in(a) and vague_in(b)
    vague_caught = vague and a.specificity <= VAGUE_CAUGHT_AT and b.specificity <= VAGUE_CAUGHT_AT
    if vague:
        note = (a if a.vagueness_flags else b).explanation
        explanation = f"{reason_line('vague')} Judge’s note: {note}"
    else:
        explanation = a.explanation
    sharp = (not vague and all(v.specificity == v.original_specificity for v in (a, b))
             and spec >= SHARP_AT)
    return Ruling(valid=True, reason="", explanation=explanation, vague=vague,
                  vague_caught=vague_caught, sharp=sharp, **base)


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
    from app.diffing import word_diff
    # One change: its words. Several: newline-joined, which reason_line treats as "several".
    added = "\n".join(c.after for c in word_diff(original, edited).changes if c.after)
    return rule(a, b, judge=judge.name, model=getattr(judge, "model", None), added=added)
