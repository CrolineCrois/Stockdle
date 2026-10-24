"""A rule-based stand-in for the LLM judge, for development without a key.

It is generous: almost any change to a content word counts as "false". That
keeps the game playable offline, but its verdicts are not research data --
every verdict it writes is tagged ``"judge": "mock"`` in the attempt log, and
analytics should filter those out.
"""

from __future__ import annotations

from app.diffing import norm, word_diff
from app.lexicon import ABSURD, ANTONYMS, CAUSAL, NEGATIONS, is_entity, is_number

from .base import Verdict

# Swaps that keep the meaning: changing one of these for its partner is not a lie.
SYNONYMS = {frozenset(p) for p in [
    ("says", "said"), ("says", "claims"), ("big", "large"), ("major", "big"),
    ("talks", "discussions"), ("us", "u.s."), ("uk", "britain"), ("pm", "minister"),
]}
FUNCTION_WORDS = {"a", "an", "the", "of", "to", "in", "on", "for", "and", "as", "at", "by",
                  "with", "is", "are", "was", "be", "its", "it", "this", "that"}
HEDGES = {"may", "might", "could", "reportedly", "allegedly", "possibly", "some", "many",
          "several", "narrowly", "sources", "unnamed", "perhaps", "likely"}
QUANTIFIERS = {"all", "none", "most", "few", "every", "no", "half", "majority", "minority"}
TEMPORAL = {"before", "after", "yesterday", "today", "tomorrow", "monday", "tuesday",
            "wednesday", "thursday", "friday", "saturday", "sunday", "week", "month", "year"}


def _specificity(text: str) -> int:
    words = text.split()
    concrete = sum(1 for w in words if is_number(w.strip(".,:;'\"")) or is_entity(w.strip(".,:;'\"")))
    hedged = sum(1 for w in words if norm(w) in HEDGES)
    return max(1, min(5, 2 + concrete - 2 * hedged))


class MockJudge:
    name = "mock"

    def judge(self, original: str, snippet: str, edited: str, phrasing: str = "a") -> Verdict:
        diff = word_diff(original, edited)
        before = [w for c in diff.changes for w in c.before.split()]
        after = [w for c in diff.changes for w in c.after.split()]
        nb, na = [norm(w) for w in before], [norm(w) for w in after]

        edit_type, is_false, why = "other", False, "Nothing checkable changed."
        if any(is_number(w) for w in before + after):
            edit_type, is_false, why = "number", True, "A number was changed."
        elif any(w in QUANTIFIERS for w in nb + na):
            edit_type, is_false, why = "quantifier", True, "How many was changed."
        elif any(w in TEMPORAL for w in nb + na):
            edit_type, is_false, why = "temporal", True, "When it happened was changed."
        elif any(w in NEGATIONS for w in nb + na) or any(ANTONYMS.get(b) == a for b, a in zip(nb, na)):
            edit_type, is_false, why = "negation", True, "The claim was reversed."
        elif any(is_entity(w) for w in before + after):
            edit_type, is_false, why = "entity swap", True, "A name or place was swapped."
        elif any(w in CAUSAL for w in na):
            edit_type, is_false, why = "causal", True, "A cause or consequence was added."
        elif any(w not in FUNCTION_WORDS for w in nb + na):
            pairs = {frozenset((b, a)) for b, a in zip(nb, na)}
            if not pairs or not pairs <= SYNONYMS:
                is_false, why = True, "A content word was changed."
            else:
                why = "That is a synonym swap; the facts did not change."

        words = edited.split()
        plausible = (4 <= len(words) <= 30 and not any(norm(w) in ABSURD for w in words)
                     and "!!" not in edited)
        grammatical = not any(norm(x) == norm(y) and norm(x)
                              for x, y in zip(words, words[1:]))
        if not plausible:
            why = "Nobody would believe that."
        content = [w for w in nb + na if w and w not in FUNCTION_WORDS]
        materiality = 1 if not content else (4 if is_false else 2)
        flags = [f"added hedge: {w}" for w in na if w in HEDGES]
        return Verdict(is_false=is_false, is_plausible=plausible, is_grammatical=grammatical,
                       materiality=materiality, specificity=_specificity(edited),
                       original_specificity=_specificity(original), vagueness_flags=flags,
                       edit_type=edit_type, explanation=f"[mock judge] {why}")
