"""What the first-glance meter reads alongside the headline.

Not the one-line RSS snippet: the passage of the source article that best
matches the original headline -- the evidence the verifier is most likely to
read on submit. That makes the meter a cheap preview of the real verdict
instead of a style guess. Cached per headline; falls back to the snippet when
an article has no fetched body.
"""

from __future__ import annotations

from functools import lru_cache

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Headline, Passage

_TOKEN_STOP = {"the", "a", "an", "of", "to", "in", "on", "for", "and", "is", "are", "was", "be",
               "as", "at", "by", "with", "it", "its", "this", "that", "from", "has", "have", "said"}


def _tokens(text: str) -> set[str]:
    import re
    return {t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in _TOKEN_STOP}


def best_passage(headline: Headline, passages: list[Passage]) -> str:
    if not passages:
        return headline.snippet or ""     # never the headline itself: that is the answer key
    q = _tokens(headline.text)
    return max(passages, key=lambda p: (len(q & _tokens(p.text)), -p.idx)).text


@lru_cache(maxsize=4096)
def premise_for(headline_id: int) -> str:
    with SessionLocal() as db:
        h = db.get(Headline, headline_id)
        if h is None:
            return ""
        ps = list(db.scalars(select(Passage).where(Passage.headline_id == headline_id)).all())
        return best_passage(h, ps)
