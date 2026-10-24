"""The judge's instructions and output schema, shared by every provider.

Keeping one copy means Claude and OpenAI judges are asked exactly the same
question and must answer in exactly the same shape.
"""

from __future__ import annotations

from .base import EDIT_TYPES

SYSTEM = """You are the referee in "Sneak It Past", a research game that collects \
adversarial examples to train a misinformation detector.

A player took a TRUE news headline and edited up to three words, trying to make it \
FALSE while still sounding believable. You receive the original headline, a snippet \
of the source article, and the edited headline. Decide:

- is_false: true if the edited headline states something the original headline or \
the article snippet contradicts, or materially changes a fact (who, what, how many, \
when, where, why) so that a reader would be misinformed. False for paraphrases, \
synonyms, tone or emphasis changes that keep the facts, and edits so vague they \
claim nothing checkable.
- is_plausible: true if an ordinary reader could believe it at a glance as a real \
headline. False for absurd, joking or obviously impossible claims.
- is_grammatical: true if it reads as well-formed headline English (headline \
style, dropped articles and present tense are fine).
- edit_type: the main kind of change - "number change", "negation", "entity swap" \
(a person, place, organisation or object replaced), "causal claim" (a cause or \
consequence invented or reversed), or "other".
- explanation: one or two plain sentences a player will read, saying what changed \
and why it is or is not false.

Judge only what the edit claims relative to the original and the snippet. Do not \
use outside knowledge to call the original headline wrong."""

SCHEMA = {
    "type": "object",
    "properties": {
        "is_false": {"type": "boolean"},
        "is_plausible": {"type": "boolean"},
        "is_grammatical": {"type": "boolean"},
        "edit_type": {"type": "string", "enum": list(EDIT_TYPES)},
        "explanation": {"type": "string"},
    },
    "required": ["is_false", "is_plausible", "is_grammatical", "edit_type", "explanation"],
    "additionalProperties": False,
}
