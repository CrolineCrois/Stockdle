"""Train detector v0: a small NLI transformer on true headlines vs machine-made fakes.

    python -m detector.train_v0              # makes fakes first if there are none
    python -m detector.train_v0 --epochs 4

v0 is the baseline the game exists to beat: it has only ever seen lies written
by a machine (Claude or OpenAI when a key is set, the rule generator otherwise
-- the version's note records which). It ships only if it passes the
held-out quality gate (``evaluate.ship_check``). Human exploits collected in play are what
patch days add on top.

The split is by headline and is saved to ``data/detectors/split.json``; every
later version keeps those headlines out of training, so the synthetic test set
stays comparable across versions.
"""

from __future__ import annotations

import argparse

from sqlalchemy import select

from app import config
from app.db import SessionLocal, init_db
from app.models import Headline, SyntheticFake
from ingest.make_fakes import generate

from . import registry
from .bounties import refresh as refresh_bounties
from .transformer import finetune
from .evaluate import metrics, ship_check
from .splits import synthetic_examples, train_val_test

NAME = "v0"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=4)
    ap.add_argument("--lr", type=float, default=2e-5)
    ap.add_argument("--batch-size", type=int, default=8)
    ap.add_argument("--keep-current", action="store_true", help="don't make v0 live")
    args = ap.parse_args()

    init_db()
    with SessionLocal() as db:
        if db.scalar(select(SyntheticFake.id).limit(1)) is None:
            print(f"[v0] no fakes yet: {generate(use_rules=False)}")
        heads = list(db.scalars(select(Headline).where(Headline.active)).all())
        # Prefer LLM-made fakes when they exist; otherwise the rule-made ones.
        gens = set(db.scalars(select(SyntheticFake.generator)).all())
        generator = next((g for g in ("claude", "openai") if g in gens), "rules")
        train_h, val_h, test_h = train_val_test(heads)
        tr_pairs, tr_labels = synthetic_examples(db, train_h, generator)
        te_pairs, te_labels = synthetic_examples(db, test_h, generator)
        val_true = [(h.text, h.snippet) for h in val_h]

    print(f"[v0] training on {len(tr_labels)} pairs ({sum(tr_labels)} fakes, generator={generator})")
    det = finetune(NAME, config.DETECTOR_BASE_MODEL, tr_pairs, tr_labels, epochs=args.epochs,
                   lr=args.lr, batch_size=args.batch_size)
    threshold = det.fit_threshold(val_true)
    print(f"[v0] calibrated on {len(val_true)} validation headlines: raw threshold {threshold:.3f}")
    held_out = metrics(det, te_pairs, te_labels)
    path = det.save(config.DETECTOR_DIR / NAME)
    llm = {"claude": config.FAKES_MODEL, "openai": config.OPENAI_FAKES_MODEL}.get(generator)
    base = config.DETECTOR_BASE_MODEL.split("/")[-1]
    note = (f"{base} on true headlines vs {generator}-made fakes "
            f"({'LLM: ' + llm if llm else 'no API key: rule-based'})")
    ok, why = ship_check(held_out)
    if not ok:
        note += f" -- NOT shipped: {why}"
    registry.register(NAME, det.kind, path, n_train=len(tr_labels),
                      metrics={"synthetic_test": held_out, "fake_generator": generator,
                               "shipped": ok},
                      note=note, make_current=ok and not args.keep_current)
    print(f"[v0] held-out synthetic test: {held_out}")
    if not ok:
        print(f"[v0] NOT made live: {why}. The previous detector stays current.")
    print(f"[v0] current detector: {registry.current_name()}")
    print(f"[v0] flagged {refresh_bounties()} bounty headlines")


if __name__ == "__main__":
    main()
