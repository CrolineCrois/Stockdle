"""Numbers for the analytics dashboard (/lab).

``judge="real"`` keeps only attempts the Claude judge ruled on; ``"all"`` also
counts mock-judged ones (development without a key). The page always says
which it is showing and how many mock-judged attempts exist.

Version comparisons score every detector on the *same* held-out exploits
(see ``detector.patch_day.is_holdout``) and the same synthetic test set, so a
version is never graded on data it trained on. Those predictions are the slow
part, so they are cached per (version, evaluation-set) and each model is loaded
only for the duration of its own scoring.
"""

from __future__ import annotations

import json
import time
import threading
from collections import Counter

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from detector import registry
from detector.evaluate import catch_rate, metrics

from . import config, review
from .diffing import norm
from .db import SessionLocal
from .models import Attempt, DetectorVersion, Headline, Player, Round

STOPWORDS = {"a", "an", "the", "of", "to", "in", "on", "for", "and", "as", "at", "by", "with",
             "is", "are", "was", "be", "its", "it", "this", "that", "from", "has", "have"}
_version_cache: dict[tuple, dict] = {}


def _judge_of(a: Attempt) -> str | None:
    return json.loads(a.judge_output_json or "{}").get("judge")


def _attempts(db: Session, judge: str) -> list[Attempt]:
    rows = db.scalars(select(Attempt)).all()
    if judge == "real":
        # Timeouts are never judged; keep them, they say nothing about the judge.
        rows = [a for a in rows if a.outcome == "timeout" or _judge_of(a) not in (None, "mock")]
    return rows


VERSION_TTL_S = 1800
_version_state: dict = {"rows": [], "at": 0.0, "running": False}
_version_lock = threading.Lock()


def _version_rows(db: Session, exploits: list[Attempt]) -> list[dict]:
    """Meter versions scored on held-out data. Scoring runs thousands of model
    calls, so it happens in a background thread at most every VERSION_TTL_S;
    requests always get the latest finished result immediately (it used to be
    recomputed whenever a new exploit appeared, which pinned the CPU under
    public load)."""
    with _version_lock:
        stale = time.monotonic() - _version_state["at"] > VERSION_TTL_S or not _version_state["rows"]
        if stale and not _version_state["running"]:
            _version_state["running"] = True
            threading.Thread(target=_refresh_versions, daemon=True).start()
        return list(_version_state["rows"])


def _refresh_versions() -> None:
    try:
        with SessionLocal() as db:
            exploits = [a for a in db.scalars(select(Attempt)).all() if a.outcome == "snuck"]
            rows = _compute_version_rows(db, exploits)
        with _version_lock:
            _version_state["rows"], _version_state["at"] = rows, time.monotonic()
    finally:
        with _version_lock:
            _version_state["running"] = False


def _compute_version_rows(db: Session, exploits: list[Attempt]) -> list[dict]:
    from detector.patch_day import is_holdout
    from detector.splits import SPLIT_FILE, synthetic_examples

    heads = {h.id: h for h in db.scalars(select(Headline)).all()}
    hold = [a for a in exploits if is_holdout(a.id)]
    hold_pairs = [(a.edited_headline, heads[a.headline_id].snippet) for a in hold]
    test_ids = set(json.loads(SPLIT_FILE.read_text())["test"]) if SPLIT_FILE.exists() else set()
    test_heads = [h for hid, h in heads.items() if hid in test_ids]
    syn_pairs, syn_labels = synthetic_examples(db, test_heads)
    syn_fakes = [p for p, y in zip(syn_pairs, syn_labels) if y == 1]
    true_pairs = [(h.text, h.snippet) for h in test_heads]

    out = []
    for v in db.scalars(select(DetectorVersion).order_by(DetectorVersion.created_at)).all():
        key = (v.name, v.path, tuple(a.id for a in hold), len(syn_fakes), len(true_pairs))
        if key not in _version_cache:
            try:
                det = registry.load(v.name)
            except Exception as exc:  # noqa: BLE001 - a missing model shouldn't sink the page
                _version_cache[key] = {"error": f"{type(exc).__name__}: {exc}"}
            else:
                _version_cache[key] = {
                    "human_catch": catch_rate(det, hold_pairs),
                    "machine_catch": catch_rate(det, syn_fakes),
                    "false_alarm": metrics(det, true_pairs, [0] * len(true_pairs)).get("false_alarm_rate"),
                }
                if v.name != registry.current_name():
                    registry.evict(v.name)
        out.append({"name": v.name, "kind": v.kind, "note": v.note, "n_train": v.n_train,
                    "is_current": v.is_current, "created_at": v.created_at.isoformat() + "Z",
                    "n_human": len(hold_pairs), "n_machine": len(syn_fakes),
                    "n_true": len(true_pairs), **_version_cache[key]})
    return out


def _time_buckets(attempts: list[Attempt]) -> list[dict]:
    """Success rate and mean suspicion by how much of the clock was left."""
    edges = [(0.0, 0.25, "0–25%"), (0.25, 0.5, "25–50%"), (0.5, 0.75, "50–75%"), (0.75, 1.01, "75–100%")]
    scored = [a for a in attempts if a.outcome in ("snuck", "caught", "timeout") and a.timer_start_seconds]
    rows = []
    for lo, hi, label in edges:
        inside = [a for a in scored
                  if lo <= (a.time_remaining_at_submit / a.timer_start_seconds) < hi]
        susp = [a.suspicion_score_final for a in inside if a.suspicion_score_final is not None]
        rows.append({
            "bucket": label, "n": len(inside),
            "success_rate": round(sum(a.outcome == "snuck" for a in inside) / len(inside), 4) if inside else None,
            "avg_suspicion": round(sum(susp) / len(susp), 4) if susp else None,
        })
    return rows


def _verifier_failures(attempts: list[Attempt]) -> list[dict]:
    """Of the judge-valid lies of each edit type, how many did the verifier miss?"""
    lies = [a for a in attempts if a.outcome in ("snuck", "partial", "caught") and a.verifier_verdict]
    out = []
    for kind in sorted({a.edit_type or "other" for a in lies}):
        group = [a for a in lies if (a.edit_type or "other") == kind]
        missed = [float(a.outcome in ("snuck", "partial")) for a in group]
        from evaluation.metrics import ci
        out.append({"edit_type": kind, "n": len(group), "failure_rate": ci(missed),
                    "supported": sum(a.verifier_verdict == "supported" for a in group),
                    "nei": sum(a.verifier_verdict == "nei" for a in group)})
    return sorted(out, key=lambda r: -(r["failure_rate"]["value"] or 0))


def _mode_win_rates(attempts: list[Attempt]) -> list[dict]:
    rows = []
    for mode in ("evidence", "breaking"):
        group = [a for a in attempts if a.mode == mode and a.outcome in ("snuck", "partial", "caught")
                 and a.verifier_verdict]
        rows.append({"mode": mode, "n": len(group),
                     "snuck": sum(a.outcome == "snuck" for a in group),
                     "partial": sum(a.outcome == "partial" for a in group),
                     "win_rate": round(sum(a.outcome == "snuck" for a in group) / len(group), 4)
                     if group else None})
    return rows


def _progress(attempts: list[Attempt]) -> list[dict]:
    """Approved exploits per day, cumulative, by edit type."""
    approved = sorted((a for a in attempts if a.review_status == "approved"),
                      key=lambda a: a.reviewed_at or a.created_at)
    running: Counter = Counter()
    days: dict[str, dict] = {}
    for a in approved:
        running[a.edit_type or "other"] += 1
        day = (a.reviewed_at or a.created_at).date().isoformat()
        days[day] = {"day": day, "total": sum(running.values()), **dict(running)}
    return list(days.values())


def _evaluation() -> dict | None:
    from evaluation.data import EVAL_DIR
    path = EVAL_DIR / "latest.json"
    return json.loads(path.read_text()) if path.exists() else None


def build(db: Session, judge: str = "all") -> dict:
    attempts = _attempts(db, judge)
    exploits = [a for a in attempts if a.outcome == "snuck"]
    by_type = Counter(a.edit_type or "other" for a in exploits)
    added = Counter(norm(w) for a in exploits for c in a.changed_words for w in c["after"].split()
                    if norm(w) and norm(w) not in STOPWORDS)
    removed = Counter(norm(w) for a in exploits for c in a.changed_words for w in c["before"].split()
                      if norm(w) and norm(w) not in STOPWORDS)
    all_attempts = db.scalars(select(Attempt)).all()
    mock_n = sum(1 for a in all_attempts if _judge_of(a) == "mock")

    return {
        "judge_filter": judge,
        "mock_judged_attempts": mock_n,
        "totals": {
            "rounds_played": db.scalar(select(func.count(Round.id)).where(Round.status != "active")) or 0,
            "attempts": len(attempts),
            "exploits": len(exploits),
            "patched": sum(1 for a in exploits if a.patched_in),
            "zero_days": sum(1 for a in exploits if a.is_novel),
            "players": db.scalar(select(func.count(Player.id)).where(~Player.is_bot)) or 0,
            "current_detector": registry.current_name(),
        },
        "versions": _version_rows(db, exploits),
        "edit_types": [{"edit_type": k, "count": v} for k, v in by_type.most_common()],
        "words_added": [{"word": k, "count": v} for k, v in added.most_common(12)],
        "words_removed": [{"word": k, "count": v} for k, v in removed.most_common(12)],
        "timer": _time_buckets(attempts),
        "outcomes": dict(Counter(a.outcome for a in attempts)),
        "threshold": config.SNEAK_THRESHOLD,
        "verifier_failures": _verifier_failures(attempts),
        "modes": _mode_win_rates(attempts),
        "review": review.stats(db),
        "progress": _progress(attempts),
        "evaluation": _evaluation(),
    }
