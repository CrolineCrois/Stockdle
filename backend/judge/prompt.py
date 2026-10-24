"""The judge's instructions and output schema, shared by every provider.

Two phrasings of the same rubric: the judge runs once with each, and both must
agree that the edit is false (see ``base.rule``). Same schema either way, so
Claude and OpenAI judges answer in exactly the same shape.
"""

from __future__ import annotations

from .base import EDIT_TYPES

RUBRIC = """Scores, each 1-5:

materiality - would an ordinary reader come away believing something false AND
meaningful?
  1: pedantic, no real change in meaning ("the" -> "a"; "says" -> "said")
  3: a real but minor factual change
  5: changes what happened ("votes for" -> "votes against"; "acquitted" -> "convicted")

specificity - how concrete and checkable a claim is. Score the original headline
and the edited headline on the same scale.
  1-2: vague ("narrowly", "many", "may", "reportedly", "some say", "unnamed sources")
  3: partly concrete
  4-5: sharp - precise numbers, named people, places, dates ("52-48", "Lyon", "Tuesday")
  A precise-but-wrong number or a swapped name keeps specificity high: that is a
  sharp lie. Replacing "52-48" with "narrowly", or adding "may" / "reportedly" /
  "some say", lowers it.

vagueness_flags - short notes for every hedge or blur the edit introduced, e.g.
"added hedge: may", "number replaced with 'many'", "attributed to unnamed sources".
Empty if none.

edit_type - the main kind of change: "number", "role swap" (who did what to whom
reversed), "causal" (a cause or consequence invented or reversed), "temporal"
(when, or the order of events), "negation", "quantifier" (all/some/none,
most/few), "entity swap" (a different person, place, organisation or thing), or
"other"."""

SYSTEM_A = """You are the referee in "Sneak It Past", a research game that collects \
adversarial examples to train a fact-checking model.

A player took a TRUE news headline and edited up to three words, trying to make it \
FALSE while still sounding believable. You receive the original headline, a snippet \
of the source article, and the edited headline. Decide:

- is_false: true if the edited headline states something the original or the snippet \
contradicts, or materially changes a fact (who, what, how many, when, where, why) so \
that a reader would be misinformed. False for paraphrases, synonyms, emphasis \
changes that keep the facts, and edits too vague to claim anything checkable.
- is_plausible: an ordinary reader could believe it at a glance as a real headline.
- is_grammatical: well-formed headline English (headline style is fine).

""" + RUBRIC + """

explanation: one or two plain sentences a player will read, saying what changed and \
why it is or is not a meaningful lie.

Judge only what the edit claims relative to the original and the snippet. Do not use \
outside knowledge to call the original headline wrong."""

SYSTEM_B = """You are a careful fact-checker reviewing a single edit to a news \
headline, as part of a study of how fact-checking models fail.

The ORIGINAL headline is accurate. Someone changed up to three words to produce the \
EDITED headline. A snippet of the source article is included. Answer as a checklist:

1. After reading only the edited headline, would a reader hold a belief that the \
original or the snippet shows to be wrong? That is is_false. A reworded but \
equivalent headline, or one so hedged it asserts nothing checkable, is not false.
2. Would it pass as a real headline to a casual reader? That is is_plausible.
3. Is it grammatical in headline style? That is is_grammatical.
4. Rate it on the rubric below.

""" + RUBRIC + """

explanation: one or two sentences, written for the person who made the edit.

Base every answer on the original headline and the snippet only."""

PROMPTS = {"a": SYSTEM_A, "b": SYSTEM_B}
SYSTEM = SYSTEM_A      # kept for callers that use a single phrasing

SCHEMA = {
    "type": "object",
    "properties": {
        "is_false": {"type": "boolean"},
        "is_grammatical": {"type": "boolean"},
        "is_plausible": {"type": "boolean"},
        "materiality": {"type": "integer", "enum": [1, 2, 3, 4, 5]},
        "specificity": {"type": "integer", "enum": [1, 2, 3, 4, 5]},
        "original_specificity": {"type": "integer", "enum": [1, 2, 3, 4, 5]},
        "vagueness_flags": {"type": "array", "items": {"type": "string"}},
        "edit_type": {"type": "string", "enum": list(EDIT_TYPES)},
        "explanation": {"type": "string"},
    },
    "required": ["is_false", "is_grammatical", "is_plausible", "materiality", "specificity",
                 "original_specificity", "vagueness_flags", "edit_type", "explanation"],
    "additionalProperties": False,
}


def user_message(original: str, snippet: str, edited: str) -> str:
    return (f"Original headline: {original}\n\n"
            f"Article snippet: {snippet or '(none)'}\n\n"
            f"Edited headline: {edited}")
