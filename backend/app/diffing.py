"""Word-level diff between the original headline and the player's edit.

A "word change" is one substituted, inserted or deleted word. Replacing two
words with three counts as three changes (the longer side of the swap), so
"rose 5%" -> "fell sharply by 9%" is 4 changes, not 1.

Words are compared with case and surrounding punctuation stripped, so fixing
capitalisation or adding a comma is never a change -- and never a way to
"edit" a headline without changing what it says.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher

_EDGE_PUNCT = re.compile(r"^[^\w$£€%]+|[^\w$£€%]+$")


def tokens(text: str) -> list[str]:
    return text.split()


def norm(word: str) -> str:
    return _EDGE_PUNCT.sub("", word).lower()


@dataclass
class Change:
    op: str              # "replace" | "insert" | "delete"
    before: str          # original words ("" for an insert)
    after: str           # edited words ("" for a delete)
    count: int           # word changes this op costs

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Diff:
    changes: list[Change]

    @property
    def num_changes(self) -> int:
        return sum(c.count for c in self.changes)

    @property
    def changed_words(self) -> list[dict]:
        return [c.to_dict() for c in self.changes]


def word_diff(original: str, edited: str) -> Diff:
    a, b = tokens(original), tokens(edited)
    na = [norm(w) for w in a]
    nb = [norm(w) for w in b]
    changes: list[Change] = []
    for op, i1, i2, j1, j2 in SequenceMatcher(a=na, b=nb, autojunk=False).get_opcodes():
        if op == "equal":
            continue
        before, after = " ".join(a[i1:i2]), " ".join(b[j1:j2])
        # Tokens that differ only in punctuation (e.g. "deal" vs "deal,") are
        # equal after norm(); a token that is *only* punctuation normalises to
        # "" -- adding or removing one is not a word change either.
        real_before = [w for w in na[i1:i2] if w]
        real_after = [w for w in nb[j1:j2] if w]
        if real_before == real_after:
            continue
        changes.append(Change(op=op, before=before, after=after,
                              count=max(len(real_before), len(real_after))))
    return Diff(changes)
