"""The shared train/test split by headline, used by every detector version.

A fixed ~20% of headlines (saved in ``data/detectors/split.json``, extended as
new headlines arrive) is never trained on by any version, so the synthetic
test set means the same thing for the stub, v0 and every patch.

Of the rest, a stable ~15% is the *validation* slice: not trained on either,
used only to set each version's calibration threshold (see transformer.py), so
the test set never influences anything that ships.
"""

from __future__ import annotations

import hashlib
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
    """(pairs, labels) for the given headlines and their synthetic fakes.

    Each pair is (headline, premise), where the premise is the source passage
    the meter reads at play time (``detector.premise``), so training matches use.
    """
    from .premise import premise_for
    q = select(SyntheticFake).where(SyntheticFake.headline_id.in_([h.id for h in heads]))
    if generator:
        q = q.where(SyntheticFake.generator == generator)
    by_id = {h.id: h for h in heads}
    pairs = [(h.text, premise_for(h.id)) for h in heads]
    labels = [0] * len(heads)
    for f in db.scalars(q).all():
        pairs.append((f.text, premise_for(f.headline_id)))
        labels.append(1)
    return pairs, labels


def is_validation(headline_id: int) -> bool:
    h = int(hashlib.sha1(f"val-{headline_id}".encode()).hexdigest()[:8], 16)
    return (h % 1000) < 150


def train_val_test(heads: list[Headline]) -> tuple[list[Headline], list[Headline], list[Headline]]:
    test_ids = load_split(heads)
    test = [h for h in heads if h.id in test_ids]
    rest = [h for h in heads if h.id not in test_ids]
    val = [h for h in rest if is_validation(h.id)]
    train = [h for h in rest if not is_validation(h.id)]
    return train, val, test
