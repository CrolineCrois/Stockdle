"""Novelty: is this exploit a new trick, or a variation on one we've seen?

An edit is embedded as two parts, each a unit vector from a small sentence
transformer (all-MiniLM-L6-v2):

    shift    emb(edited headline) - emb(original headline), normalised:
             *what the edit did to the meaning*, independent of the topic
    words    emb("<removed words> -> <added words>"):
             *the move itself* ("rises -> falls", "+ not", "Paris -> Lyon")

concatenated and normalised. The novelty distance is the minimum cosine
distance to every earlier successful exploit; above ``NOVELTY_THRESHOLD`` it is
a "zero-day exploit": +50% points and a place on the Exploit Board.

If sentence-transformers is not installed, novelty is simply skipped (no bonus,
distance logged as null) -- the game still works.
"""

from __future__ import annotations

import json
import threading
from functools import lru_cache

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import config
from .models import Attempt

MODEL = "sentence-transformers/all-MiniLM-L6-v2"
_lock = threading.Lock()


@lru_cache(maxsize=1)
def _encoder():
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        return None
    return SentenceTransformer(MODEL, device="cpu")


def available() -> bool:
    return _encoder() is not None


def _unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-9 else v


def embed_edit(original: str, edited: str, changes: list[dict]) -> list[float] | None:
    enc = _encoder()
    if enc is None:
        return None
    removed = " ".join(c["before"] for c in changes if c["before"]) or "(nothing)"
    added = " ".join(c["after"] for c in changes if c["after"]) or "(nothing)"
    with _lock:
        a, b, w = enc.encode([original, edited, f"{removed} -> {added}"],
                             normalize_embeddings=True)
    vec = _unit(np.concatenate([_unit(b - a), w]))
    return [round(float(x), 5) for x in vec]


def min_distance(db: Session, vec: list[float]) -> float:
    """Cosine distance to the closest earlier successful exploit (1.0 if none)."""
    rows = db.scalars(select(Attempt.edit_embedding_json).where(
        Attempt.outcome == "snuck", Attempt.edit_embedding_json != "")).all()
    if not rows:
        return 1.0
    mat = np.asarray([json.loads(r) for r in rows], dtype=np.float32)
    sims = mat @ np.asarray(vec, dtype=np.float32)
    return round(float(1.0 - sims.max()), 4)


def assess(db: Session, original: str, edited: str, changes: list[dict]):
    """(embedding, distance, is_novel) -- all None/False when novelty is unavailable."""
    vec = embed_edit(original, edited, changes)
    if vec is None:
        return None, None, False
    dist = min_distance(db, vec)
    return vec, dist, dist >= config.NOVELTY_THRESHOLD
