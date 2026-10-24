"""Train the phase-1 stub detector.

    python -m detector.train_stub

True headlines (label 0) come from the headlines table; false ones (label 1)
are rule-made edits of them (``ingest.perturb``). The split is by *headline*,
so no true headline's fakes leak between train and test. The stub becomes the
current detector only if there is no current detector yet (a real v0 should
never be silently replaced by the stub); pass ``--make-current`` to force it.
"""

from __future__ import annotations

import argparse
import json
import random

from sklearn.metrics import accuracy_score, roc_auc_score
from sqlalchemy import select

from app import config
from app.db import SessionLocal, init_db
from app.models import DetectorVersion, Headline
from ingest.perturb import entity_pool, make_fakes

from . import registry
from .baseline import BaselineDetector
from .bounties import refresh as refresh_bounties

NAME = "stub"


def build_examples(headlines: list[Headline], rng: random.Random):
    pool = entity_pool([h.text for h in headlines])
    pairs, labels = [], []
    for h in headlines:
        pairs.append((h.text, h.snippet))
        labels.append(0)
        for fake, _kind in make_fakes(h.text, pool, rng):
            pairs.append((fake, h.snippet))
            labels.append(1)
    return pairs, labels


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--make-current", action="store_true")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    init_db()
    rng = random.Random(args.seed)
    with SessionLocal() as db:
        heads = list(db.scalars(select(Headline).where(Headline.active)).all())
    if len(heads) < 20:
        raise SystemExit("need at least 20 headlines; run `python -m ingest.seed` first")

    rng.shuffle(heads)
    cut = int(len(heads) * 0.8)
    tr_pairs, tr_labels = build_examples(heads[:cut], rng)
    te_pairs, te_labels = build_examples(heads[cut:], rng)

    held_out = BaselineDetector.train(NAME, tr_pairs, tr_labels)
    probs = held_out.predict(te_pairs)
    metrics = {
        "test_auc": round(float(roc_auc_score(te_labels, probs)), 4),
        "test_acc": round(float(accuracy_score(te_labels, [p >= 0.5 for p in probs])), 4),
        "n_test": len(te_labels),
        "train_data": "seed headlines + rule-made fakes",
    }

    # Ship a model trained on everything; the metrics above stay honest.
    all_pairs, all_labels = tr_pairs + te_pairs, tr_labels + te_labels
    final = BaselineDetector.train(NAME, all_pairs, all_labels)
    path = final.save(config.DETECTOR_DIR / NAME)

    with SessionLocal() as db:
        row = db.scalar(select(DetectorVersion).where(DetectorVersion.name == NAME))
        if row is None:
            row = DetectorVersion(name=NAME, kind="baseline", path=str(path))
            db.add(row)
        row.n_train, row.metrics_json = len(all_labels), json.dumps(metrics)
        row.note = "phase-1 stub: logistic regression on headline-vs-snippet features"
        has_current = db.scalar(select(DetectorVersion).where(DetectorVersion.is_current))
        db.commit()
    registry.forget()
    if args.make_current or has_current is None:
        registry.set_current(NAME)
    print(f"[stub] trained on {len(all_labels)} examples; held-out {metrics}")
    print(f"[stub] current detector: {registry.current_name()}")
    print(f"[stub] flagged {refresh_bounties()} bounty headlines")


if __name__ == "__main__":
    main()
