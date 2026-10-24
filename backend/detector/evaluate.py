"""One way to measure every detector version, so versions are comparable.

    catch_rate        share of false headlines scored >= 0.5 (caught)
    false_alarm_rate  share of true headlines scored >= 0.5 (wrongly flagged)
    accuracy, auc     over both together
"""

from __future__ import annotations

from sklearn.metrics import roc_auc_score

from app import config

from .base import Detector


def metrics(det: Detector, pairs: list[tuple[str, str]], labels: list[int]) -> dict:
    if not pairs:
        return {"n": 0}
    probs = det.predict(pairs)
    caught = [p >= config.SNEAK_THRESHOLD for p in probs]
    fakes = [c for c, y in zip(caught, labels) if y == 1]
    trues = [c for c, y in zip(caught, labels) if y == 0]
    out = {
        "n": len(labels),
        "accuracy": round(sum(c == bool(y) for c, y in zip(caught, labels)) / len(labels), 4),
        "catch_rate": round(sum(fakes) / len(fakes), 4) if fakes else None,
        "false_alarm_rate": round(sum(trues) / len(trues), 4) if trues else None,
    }
    if fakes and trues:
        out["auc"] = round(float(roc_auc_score(labels, probs)), 4)
    return out


def catch_rate(det: Detector, pairs: list[tuple[str, str]]) -> float | None:
    """Share of known-false pairs the detector catches (no true examples needed)."""
    if not pairs:
        return None
    return round(sum(p >= config.SNEAK_THRESHOLD for p in det.predict(pairs)) / len(pairs), 4)


# A version only goes live if it beats these on held-out data. Training can
# collapse (e.g. call everything false): that catches every fake but makes the
# game unwinnable, so "catch rate" alone must never be the bar.
MIN_AUC = 0.6
MAX_FALSE_ALARM = 0.5


def ship_check(m: dict) -> tuple[bool, str]:
    """Is a held-out ``metrics()`` result good enough to make a version live?"""
    auc, fa = m.get("auc"), m.get("false_alarm_rate")
    if auc is None or fa is None:
        return False, "no held-out fakes and true headlines to check it on"
    if auc < MIN_AUC:
        return False, f"held-out AUC {auc} < {MIN_AUC} (it isn't telling true from false)"
    if fa >= MAX_FALSE_ALARM:
        return False, f"flags {fa:.0%} of true headlines (>= {MAX_FALSE_ALARM:.0%}); unplayable"
    return True, "ok"
