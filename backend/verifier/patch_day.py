"""Patch day: retrain the evidence verifier on approved human exploits.

    python -m verifier.patch_day             # train, gate, ship as v<n>-human
    python -m verifier.patch_day --dry-run   # train and report, don't ship

Trains on approved exploits from the TRAIN side of the evaluation split only
(the test side stays held out for ``evaluation.run``), plus their matched true
headlines, with the same settings the evaluation uses. It ships only if, on
the held-out sets, it

    catches at least as many held-out exploits as the live version, and
    raises false positives on held-out true headlines by at most 10 points.

On shipping it marks every exploit it now refutes as patched (players get a
notice), records the patch-day time so later exploits form the "fresh" test
set, and re-flags bounties.
"""

from __future__ import annotations

import argparse
import re
from datetime import datetime, timezone

from sqlalchemy import select

from app import config
from app.db import SessionLocal, init_db
from app.models import Attempt, VerifierVersion

from . import registry
from .model import aggregate
from .retrieval import retrieve
from .train import finetune

MIN_EXPLOITS = 20
MAX_FP_RISE = 0.10


def next_name() -> str:
    with SessionLocal() as db:
        names = db.scalars(select(VerifierVersion.name)).all()
    nums = [int(m.group(1)) for n in names if (m := re.fullmatch(r"v(\d+)-human", n))]
    return f"v{max(nums, default=0) + 1}-human"


def _refuted(model, claim: str) -> bool:
    hits = retrieve(claim, config.VERIFIER_TOP_K)
    return aggregate(model.score(claim, [h.text for h in hits]))[0] == "refuted"


def run(*, dry_run: bool = False, min_exploits: int = MIN_EXPLOITS, log=print) -> dict:
    from evaluation.data import human_sets, mark_patch_day
    from evaluation.metrics import false_positive, refute_recall

    init_db()
    sets = human_sets(include_pending=False)
    train = sets["train"]
    if len(train) < min_exploits:
        return {"shipped": False, "reason": f"only {len(train)} approved training exploits "
                f"(need {min_exploits})"}
    name = next_name()
    live = registry.current()
    examples = [ex for ex, _ in train] + sets["train_true"]
    log(f"[patch] {name}: {len(train)} approved exploits + {len(sets['train_true'])} true, "
        f"from {config.VERIFIER_BASE_MODEL}")
    model = finetune(name, config.VERIFIER_BASE_MODEL, examples,
                     config.DATA_DIR / "verifiers" / name, log=log)

    report = {"previous": live.name, "train_exploits": len(train)}
    for label, m in (("before", live), ("after", model)):
        report[f"holdout_recall_{label}"] = refute_recall(m, sets["test"])["overall"]
        report[f"false_positive_{label}"] = false_positive(m, sets["true_test"])["overall"]
    log(f"[patch] {report}")
    if dry_run:
        return {"shipped": False, "reason": "dry run", "name": name, **report}

    rb, ra = report["holdout_recall_before"]["value"], report["holdout_recall_after"]["value"]
    fb, fa = report["false_positive_before"]["value"], report["false_positive_after"]["value"]
    if ra is not None and rb is not None and ra < rb:
        return {"shipped": False, "reason": f"held-out recall fell ({rb} -> {ra})", **report}
    if fa is not None and fb is not None and fa - fb > MAX_FP_RISE:
        return {"shipped": False, "reason": f"false positives rose {fb} -> {fa}", **report}

    registry.register(name, str(config.DATA_DIR / "verifiers" / name), train_data="human",
                      n_train=len(examples), metrics=report,
                      note=f"patch day: {len(train)} approved human exploits", make_current=True)
    patched = 0
    with SessionLocal() as db:
        rows = db.execute(select(Attempt).where(Attempt.outcome.in_(("snuck", "partial")),
                                                Attempt.patched_in.is_(None))).scalars().all()
        for a in rows:
            if _refuted(model, a.edited_headline):
                a.patched_in = name
                patched += 1
        db.commit()
    mark_patch_day(datetime.now(timezone.utc).replace(tzinfo=None))
    from app.learning import benchmark_verifier
    report["benchmark"] = benchmark_verifier(name)     # same fixed set as every other version
    from detector.bounties import refresh
    report["bounties"] = refresh()
    log(f"[patch] shipped {name}; {patched} exploits now patched")
    return {"shipped": True, "name": name, "newly_patched": patched, **report}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--min-exploits", type=int, default=MIN_EXPLOITS)
    a = ap.parse_args()
    r = run(dry_run=a.dry_run, min_exploits=a.min_exploits)
    if not r["shipped"]:
        print(f"[patch] not shipped: {r['reason']}")


if __name__ == "__main__":
    main()
