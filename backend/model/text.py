"""Headline -> feature vector.

Default path is VADER sentiment plus a small hand-built market lexicon, which
needs no model download and loads instantly. If ``sentence-transformers`` is
installed *and* ``TAPE_USE_EMBEDDINGS=1``, all-MiniLM-L6-v2 embeddings are
appended instead; the fallback is automatic if the import or model load fails.
"""

from __future__ import annotations

import os
import re
from functools import lru_cache

import numpy as np

EMBED_MODEL = "all-MiniLM-L6-v2"
EMBED_DIM = 384

BULLISH = {
    "beats", "beat", "tops", "raises", "raised", "surge", "surges", "soars",
    "record", "buyback", "upgrade", "upgrades", "expands", "expansion",
    "strong", "wins", "lands", "premium", "acquire", "acquires", "growth",
    "profit", "rally", "outperform", "approval", "approved", "contract",
}
BEARISH = {
    "misses", "miss", "cuts", "cut", "warns", "warning", "probe", "inquiry",
    "investigation", "recall", "recalled", "resigns", "resignation", "lawsuit",
    "fine", "fined", "ban", "banned", "halts", "halt", "breach", "layoffs",
    "downgrade", "downgrades", "plunge", "slump", "weak", "softening", "delay",
    "delays", "short", "fraud", "whistleblower", "suspends", "freeze", "loses",
}
# Words that signal a big binary event rather than a direction.
SHOCK = {"breaking", "exclusive", "leaked", "emergency", "sources", "abruptly"}

_TOKEN = re.compile(r"[a-z']+")


@lru_cache(maxsize=1)
def _vader():
    try:
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
        return SentimentIntensityAnalyzer()
    except Exception:  # noqa: BLE001
        return None


@lru_cache(maxsize=1)
def _embedder():
    if os.environ.get("TAPE_USE_EMBEDDINGS", "0") != "1":
        return None
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore
        return SentenceTransformer(EMBED_MODEL)
    except Exception as exc:  # noqa: BLE001
        print(f"[model] sentence-transformers unavailable ({type(exc).__name__}); "
              f"falling back to VADER + keywords", flush=True)
        return None


def embeddings_enabled() -> bool:
    return _embedder() is not None


def lexical_features(headline: str) -> list[float]:
    """9 dims: sentiment, directional lexicon counts, shock words, presence."""
    text = (headline or "").strip()
    if not text:
        return [0.0] * 9
    tokens = _TOKEN.findall(text.lower())
    n = max(len(tokens), 1)
    bull = sum(1 for t in tokens if t in BULLISH)
    bear = sum(1 for t in tokens if t in BEARISH)
    shock = sum(1 for t in tokens if t in SHOCK)

    analyzer = _vader()
    if analyzer is not None:
        s = analyzer.polarity_scores(text)
        neg, neu, pos, comp = s["neg"], s["neu"], s["pos"], s["compound"]
    else:                       # VADER missing: lexicon-only sentiment proxy
        comp = (bull - bear) / n
        pos, neg, neu = max(comp, 0.0), max(-comp, 0.0), 1.0 - abs(comp)

    return [
        float(neg), float(neu), float(pos), float(comp),
        bull / n, bear / n, shock / n,
        (bull - bear) / n,
        1.0,                    # "a headline is present" indicator
    ]


def headline_features(headline: str) -> np.ndarray:
    base = lexical_features(headline)
    model = _embedder()
    if model is None:
        return np.asarray(base, dtype=float)
    text = (headline or "").strip()
    vec = (model.encode([text], normalize_embeddings=True)[0]
           if text else np.zeros(EMBED_DIM))
    return np.concatenate([np.asarray(base, dtype=float), np.asarray(vec, dtype=float)])


def headline_feature_dim() -> int:
    return 9 + (EMBED_DIM if embeddings_enabled() else 0)
