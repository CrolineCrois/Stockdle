"""The shared train/test split by headline, used by every detector version.

A fixed ~20% of headlines (saved in ``data/detectors/split.json``, extended as
new headlines arrive) is never trained on by any version, so the synthetic
test set means the same thing for the stub, v0 and every patch.
"""

from __future__ import annotations

import json
import random

from sqlalchemy import select

from app import config
from app.models import Headline, SyntheticFake

SPLIT_FILE = config.DETECTOR_DIR / "split.json"


def load_split(heads: list[Headline], seed: int = 7) -> set[int]:
    """Held-out headline ids: reuse the saved split, extending it for new headlines."""
    saved = json.loads(SPLIT_FILE.read_text()) if SPLIT_FILE.exists() else {"test": [], "seen": []}
    test, seen = set(saved["test"]), set(saved["seen"])
    rng = random.Random(seed)
    for h in sorted(heads, key=lambda h: h.id):
        if h.id not in seen:
            seen.add(h.id)
            if rng.random() < 0.2:
                test.add(h.id)
    SPLIT_FILE.parent.mkdir(parents=True, exist_ok=True)
    SPLIT_FILE.write_text(json.dumps({"test": sorted(test), "seen": sorted(seen)}))
    return test


def synthetic_examples(db, heads: list[Headline], generator: str | None = None):
    """(pairs, labels) for the given headlines and their synthetic fakes."""
    q = select(SyntheticFake).where(SyntheticFake.headline_id.in_([h.id for h in heads]))
    if generator:
        q = q.where(SyntheticFake.generator == generator)
    by_id = {h.id: h for h in heads}
    pairs = [(h.text, h.snippet) for h in heads]
    labels = [0] * len(heads)
    for f in db.scalars(q).all():
        pairs.append((f.text, by_id[f.headline_id].snippet))
        labels.append(1)
    return pairs, labels
