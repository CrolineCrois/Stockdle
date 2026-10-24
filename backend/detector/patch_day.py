"""Patch day: retrain the detector on the tricks players found.

    python -m detector.patch_day                # needs >= MIN_EXPLOITS new exploits
    python -m detector.patch_day --include-mock # dev only: accept mock-judged exploits
    python -m detector.patch_day --dry-run      # evaluate, don't ship

What it trains on
    Every judge-verified exploit (an edit the judge ruled false, plausible and
    grammatical, that snuck past the live detector), labelled false, each paired
    with its own original headline labelled true -- the matched set of true
    headlines. v0's synthetic training data is mixed back in so the new version
    does not forget what it already knew. It starts from the current version's
    weights: a patch, not a rebuild.

How it is measured -- honestly
    An exploit fooled whichever version was live when it was made, so scoring
    that version on it says nothing. Instead a fixed ~20% of exploits (chosen by
    a hash of the attempt id, so the set only grows) is *never* trained on, and
    every version is scored on it. False alarms on true headlines are reported
    alongside, because a detector that flags everything would "catch" every
    exploit. The synthetic test set from v0's split is re-scored too, to show
    whether patching made the detector forget.

Then it marks every exploit the new version now catches as patched in that
version (players get a notice) and re-flags bounties against the new version.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re

from sqlalchemy import select

from app import config
from app.db import SessionLocal, init_db
from app.models import Attempt, DetectorVersion, Headline

from . import registry
from .bounties import refresh as refresh_bounties
from .evaluate import catch_rate, metrics

MIN_EXPLOITS = 5
HOLDOUT_FRACTION = 0.2


def is_holdout(attempt_id: int) -> bool:
    """A stable ~20% of exploits that no version ever trains on."""
    h = int(hashlib.sha1(f"exploit-{attempt_id}".encode()).hexdigest()[:8], 16)
    return (h % 1000) < HOLDOUT_FRACTION * 1000


def exploits(db, include_mock: bool) -> list[tuple[Attempt, Headline]]:
    rows = db.execute(select(Attempt, Headline).join(Headline, Headline.id == Attempt.headline_id)
                      .where(Attempt.outcome == "snuck")).all()
    out = []
    for a, h in rows:
        judge = json.loads(a.judge_output_json or "{}").get("judge")
        if judge == "mock" and not include_mock:
            continue
        out.append((a, h))
    return out


def next_name(db) -> str:
    nums = [int(m.group(1)) for n in db.scalars(select(DetectorVersion.name)).all()
            if (m := re.fullmatch(r"v(\d+)", n))]
    return f"v{max(nums, default=0) + 1}"


def run(*, include_mock: bool = False, dry_run: bool = False, epochs: int = 4,
        min_exploits: int = MIN_EXPLOITS, log=print) -> dict:
    init_db()
    with SessionLocal() as db:
        pool = exploits(db, include_mock)
        train = [(a, h) for a, h in pool if not is_holdout(a.id)]
        hold = [(a, h) for a, h in pool if is_holdout(a.id)]
        current = db.scalar(select(DetectorVersion).where(DetectorVersion.is_current))
        name = next_name(db)
        heads = list(db.scalars(select(Headline).where(Headline.active)).all())

        if len(train) < min_exploits:
            return {"shipped": False, "reason": f"only {len(train)} trainable exploits "
                    f"(need {min_exploits})", "exploits": len(pool)}

        # Exploits + their originals (the matched true set) + v0's synthetic data.
        pairs = [(a.edited_headline, h.snippet) for a, h in train]
        labels = [1] * len(train)
        pairs += [(h.text, h.snippet) for _, h in train]
        labels += [0] * len(train)
        from .train_v0 import load_split, synthetic_examples
        test_ids = load_split(heads)
        syn_pairs, syn_labels = synthetic_examples(
            db, [h for h in heads if h.id not in test_ids])
        pairs += syn_pairs
        labels += syn_labels
        syn_test = synthetic_examples(db, [h for h in heads if h.id in test_ids])

        hold_pairs = [(a.edited_headline, h.snippet) for a, h in hold]
        true_pairs = [(h.text, h.snippet) for h in heads if h.id in test_ids]
        current_name, current_kind, current_path = current.name, current.kind, current.path

    log(f"[patch] {name}: {len(train)} exploits to learn, {len(hold)} held out, "
        f"{len(labels)} training pairs, starting from {current_name}")
    if current_kind == "distilbert":
        from .distil import finetune
        det = finetune(name, current_path, pairs, labels, epochs=epochs, log=log)
    else:
        from .baseline import BaselineDetector
        det = BaselineDetector.train(name, pairs, labels)

    before = registry.load(current_name)
    report = {
        "previous": current_name,
        "exploits_trained": len(train),
        "exploits_held_out": len(hold),
        "holdout_catch_before": catch_rate(before, hold_pairs),
        "holdout_catch_after": catch_rate(det, hold_pairs),
        "false_alarm_before": metrics(before, true_pairs, [0] * len(true_pairs)).get("false_alarm_rate"),
        "false_alarm_after": metrics(det, true_pairs, [0] * len(true_pairs)).get("false_alarm_rate"),
        "synthetic_test": metrics(det, *syn_test),
        "trained_on_mock_judge": include_mock,
    }
    log(f"[patch] {json.dumps(report)}")
    if dry_run:
        return {"shipped": False, "reason": "dry run", "name": name, **report}

    path = det.save(config.DETECTOR_DIR / name)
    note = (f"patch day: +{len(train)} human exploits on top of {current_name}"
            + (" (includes mock-judged exploits: dev only)" if include_mock else ""))
    registry.register(name, det.kind, path, n_train=len(labels), metrics=report, note=note,
                      make_current=True)

    # Which exploits does the new version now catch? Those are "patched".
    with SessionLocal() as db:
        all_snuck = db.execute(select(Attempt, Headline).join(Headline, Headline.id == Attempt.headline_id)
                               .where(Attempt.outcome == "snuck", Attempt.patched_in.is_(None))).all()
        if all_snuck:
            probs = det.predict([(a.edited_headline, h.snippet) for a, h in all_snuck])
            patched = 0
            for (a, _), p in zip(all_snuck, probs):
                if p >= config.SNEAK_THRESHOLD:
                    a.patched_in = name
                    patched += 1
            db.commit()
            report["newly_patched"] = patched
    report["bounties"] = refresh_bounties()
    log(f"[patch] shipped {name}; {report.get('newly_patched', 0)} exploits now patched")
    return {"shipped": True, "name": name, **report}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--include-mock", action="store_true",
                    help="also learn from mock-judged exploits (development only)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--epochs", type=int, default=4)
    ap.add_argument("--min-exploits", type=int, default=MIN_EXPLOITS)
    args = ap.parse_args()
    result = run(include_mock=args.include_mock, dry_run=args.dry_run, epochs=args.epochs,
                 min_exploits=args.min_exploits)
    if not result["shipped"]:
        print(f"[patch] not shipped: {result['reason']}")


if __name__ == "__main__":
    main()
