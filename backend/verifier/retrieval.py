"""BM25 retrieval over the evidence corpus (``passages``).

The index is built in memory from every passage of every active headline and
rebuilt when the corpus changes size, so a fresh scrape is picked up without
a restart. In breaking-news mode the round's own source article is excluded,
simulating a story nobody has covered yet.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass

from rank_bm25 import BM25Okapi
from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import Headline, Passage

_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = {"the", "a", "an", "of", "to", "in", "on", "for", "and", "is", "are", "was", "be",
         "as", "at", "by", "with", "it", "its", "this", "that", "from", "has", "have", "said"}


def tokens(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOP]


@dataclass
class Hit:
    passage_id: int
    headline_id: int
    text: str
    score: float


class _Index:
    def __init__(self) -> None:
        self.size = -1
        self.rows: list[tuple[int, int, str]] = []
        self.bm25: BM25Okapi | None = None
        self.lock = threading.Lock()

    def ensure(self) -> None:
        with SessionLocal() as db:
            n = db.scalar(select(func.count(Passage.id))) or 0
            if n == self.size:
                return
            rows = db.execute(select(Passage.id, Passage.headline_id, Passage.text)
                              .join(Headline, Headline.id == Passage.headline_id)
                              .where(Headline.active)).all()
        with self.lock:
            self.rows = [tuple(r) for r in rows]
            self.bm25 = BM25Okapi([tokens(t) for _, _, t in self.rows]) if self.rows else None
            self.size = n


_index = _Index()


def retrieve(claim: str, k: int = 3, exclude_headline_id: int | None = None) -> list[Hit]:
    _index.ensure()
    if _index.bm25 is None:
        return []
    query = tokens(claim)
    scores = _index.bm25.get_scores(query)
    ranked = sorted(range(len(scores)), key=lambda i: -scores[i])
    wanted = set(query)
    hits: list[Hit] = []
    for i in ranked:
        pid, hid, text = _index.rows[i]
        if exclude_headline_id is not None and hid == exclude_headline_id:
            continue
        # Require real word overlap rather than a positive score: on a small
        # corpus BM25's IDF goes negative for common terms and would hide matches.
        if not wanted & set(tokens(text)):
            continue
        hits.append(Hit(pid, hid, text, round(float(scores[i]), 3)))
        if len(hits) >= k:
            break
    return hits
