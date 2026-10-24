"""Train detector v0: DistilBERT on true headlines vs machine-made fakes.

    python -m detector.train_v0              # makes fakes first if there are none
    python -m detector.train_v0 --epochs 4

v0 is the baseline the game exists to beat: it has only ever seen lies written
by a machine (Claude when a key is set, the rule generator otherwise -- the
version's note records which). Human exploits collected in play are what
patch days add on top.

The split is by headline and is saved to ``data/detectors/split.json``; every
later version keeps those headlines out of training, so the synthetic test set
stays comparable across versions.
"""

from __future__ import annotations

import argparse
import json
import random

from sqlalchemy import select

from app import config
from app.db import SessionLocal, init_db
from app.models import Headline, SyntheticFake
from ingest.make_fakes import generate

from . import registry
from .bounties import refresh as refresh_bounties
from .distil import finetune
from .evaluate import metrics

NAME = "v0"
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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=10)
    ap.add_argument("--keep-current", action="store_true", help="don't make v0 live")
    args = ap.parse_args()

    init_db()
    with SessionLocal() as db:
        if db.scalar(select(SyntheticFake.id).limit(1)) is None:
            print(f"[v0] no fakes yet: {generate(use_rules=False)}")
        heads = list(db.scalars(select(Headline).where(Headline.active)).all())
        # Prefer LLM-made fakes when they exist; otherwise the rule-made ones.
        gens = set(db.scalars(select(SyntheticFake.generator)).all())
        generator = "claude" if "claude" in gens else "rules"
        test_ids = load_split(heads)
        train_h = [h for h in heads if h.id not in test_ids]
        test_h = [h for h in heads if h.id in test_ids]
        tr_pairs, tr_labels = synthetic_examples(db, train_h, generator)
        te_pairs, te_labels = synthetic_examples(db, test_h, generator)

    print(f"[v0] training on {len(tr_labels)} pairs ({sum(tr_labels)} fakes, generator={generator})")
    det = finetune(NAME, config.DETECTOR_BASE_MODEL, tr_pairs, tr_labels, epochs=args.epochs)
    held_out = metrics(det, te_pairs, te_labels)
    path = det.save(config.DETECTOR_DIR / NAME)
    note = (f"DistilBERT on true headlines vs {generator}-made fakes "
            f"({'LLM: ' + config.FAKES_MODEL if generator == 'claude' else 'no API key: rule-based'})")
    registry.register(NAME, "distilbert", path, n_train=len(tr_labels),
                      metrics={"synthetic_test": held_out, "fake_generator": generator},
                      note=note, make_current=not args.keep_current)
    print(f"[v0] held-out synthetic test: {held_out}")
    print(f"[v0] current detector: {registry.current_name()}")
    print(f"[v0] flagged {refresh_bounties()} bounty headlines")


if __name__ == "__main__":
    main()
