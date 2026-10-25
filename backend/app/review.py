"""Human review of exploits before they train or evaluate anything.

Exploits (snuck or partial) arrive as ``pending``. A reviewer approves or
rejects each one; only approved exploits enter training or evaluation sets.
Every decision is stored in ``reviews`` so we can report how often reviewers
agree with the judge (the judge's precision on exploits it let through).
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Attempt, Headline, Passage, Review, utcnow

EXPLOIT = ("snuck", "partial")


def queue(db: Session, status: str = "pending", limit: int = 50) -> list[dict]:
    q = (select(Attempt).where(Attempt.outcome.in_(EXPLOIT))
         .order_by(Attempt.created_at.desc()).limit(limit))
    if status == "pending":       # "" = exploits logged before review existed
        q = q.where(Attempt.review_status.in_(("pending", "")))
    elif status != "all":
        q = q.where(Attempt.review_status == status)
    out = []
    for a in db.scalars(q).all():
        ids = json.loads(a.retrieved_passage_ids_json or "[]")
        passages = []
        for pid in ids:
            p = db.get(Passage, pid)
            if p is not None:
                src = db.get(Headline, p.headline_id)
                passages.append({"text": p.text, "source": src.source if src else "",
                                 "same_story": p.headline_id == a.headline_id})
        ruling = json.loads(a.judge_output_json or "{}")
        out.append({
            "id": a.id, "created_at": a.created_at.isoformat() + "Z", "outcome": a.outcome,
            "mode": a.mode, "original": a.original_headline, "edited": a.edited_headline,
            "changes": a.changed_words, "edit_type": a.edit_type,
            "materiality": a.materiality, "specificity": a.specificity,
            "original_specificity": a.original_specificity,
            "vagueness_flags": json.loads(a.vagueness_flags_json or "[]"),
            # Vague under the CURRENT rule (both judge runs must say so), re-applied
            # to the stored runs: older rulings counted one run's flag as enough.
            "vague": _vague_now(ruling),
            "judge": ruling.get("judge"), "judge_runs": ruling.get("runs", []),
            "verifier": {"verdict": a.verifier_verdict, "version": a.verifier_version,
                         "probs": json.loads(a.verifier_probs_json or "{}")},
            "evidence": passages, "review_status": a.review_status,
            "reviewer_id": a.reviewer_id,
        })
    return out


def decide(db: Session, attempt_id: int, decision: str, reviewer: str, note: str = "") -> Attempt:
    if decision not in ("approved", "rejected"):
        raise ValueError("decision must be 'approved' or 'rejected'")
    a = db.get(Attempt, attempt_id)
    if a is None or a.outcome not in EXPLOIT:
        raise LookupError("no such exploit")
    db.add(Review(attempt_id=a.id, reviewer_id=reviewer, decision=decision, note=note[:300]))
    a.review_status, a.reviewer_id, a.reviewed_at = decision, reviewer, utcnow()
    db.commit()
    return a


def stats(db: Session) -> dict:
    """Counters for the admin page: data progress toward the first patch day."""
    attempts = db.scalars(select(Attempt)).all()
    valid = [a for a in attempts if a.outcome in ("snuck", "partial", "caught")
             and json.loads(a.judge_output_json or "{}").get("valid", True)]
    exploits = [a for a in attempts if a.outcome in EXPLOIT]
    by_type: dict[str, Counter] = defaultdict(Counter)
    for a in exploits:
        by_type[a.edit_type or "other"]["exploits"] += 1
        by_type[a.edit_type or "other"][a.review_status or "pending"] += 1
    reviewed = [a for a in exploits if a.review_status in ("approved", "rejected")]
    approved = [a for a in exploits if a.review_status == "approved"]
    return {
        "attempts": len(attempts),
        "judge_valid": len(valid),
        "exploits": len(exploits),
        "pending": sum(1 for a in exploits if a.review_status in ("", "pending")),
        "approved": len(approved),
        "rejected": len(reviewed) - len(approved),
        "target_before_patch_day": _patch_day_min(),
        # Of the exploits the judge let through, how many did a human agree with?
        "judge_precision": round(len(approved) / len(reviewed), 4) if reviewed else None,
        "decisions_logged": db.query(Review).count(),
        "by_edit_type": [{"edit_type": k, **v} for k, v in sorted(by_type.items())],
    }


def _patch_day_min() -> int:
    """The approvals a verifier patch day actually needs (it refuses with fewer)."""
    from verifier.patch_day import MIN_EXPLOITS
    return MIN_EXPLOITS



def _vague_now(ruling: dict) -> bool:
    from judge.base import VAGUE_DROP
    runs = ruling.get("runs") or []
    if len(runs) < 2:
        return bool(ruling.get("vague"))
    return all(bool(r.get("vagueness_flags")) or
               (r.get("original_specificity", r.get("specificity", 0)) - r.get("specificity", 0) >= VAGUE_DROP)
               for r in runs)
