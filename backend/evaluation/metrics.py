"""Metrics, each with a 95% bootstrap confidence interval (1,000 resamples).

    refute_recall    share of held-out lies the verifier REFUTES (catches)
    false_positive   share of held-out TRUE headlines it wrongly REFUTES
    vitaminc         accuracy and macro-F1 on a VitaminC sample (3-way)

Exploits and true headlines go through the same pipeline the game uses --
retrieve top-k passages (evidence mode), score each, aggregate -- so every
model is judged with identical evidence. VitaminC examples come with their
own evidence sentence and are scored directly.
"""

from __future__ import annotations

from collections import defaultdict

import numpy as np
from sklearn.metrics import f1_score

from verifier.model import LABELS, VerifierModel, aggregate
from verifier.retrieval import retrieve
from verifier.train import Example

RESAMPLES = 1000
SEED = 7


def ci(values: list[float], stat=np.mean) -> dict:
    """Point estimate and 95% bootstrap interval of ``stat`` over ``values``."""
    if not values:
        return {"value": None, "lo": None, "hi": None, "n": 0}
    arr = np.asarray(values, dtype=float)
    rng = np.random.default_rng(SEED)
    boots = [stat(arr[rng.integers(0, len(arr), len(arr))]) for _ in range(RESAMPLES)]
    return {"value": round(float(stat(arr)), 4), "lo": round(float(np.percentile(boots, 2.5)), 4),
            "hi": round(float(np.percentile(boots, 97.5)), 4), "n": len(arr)}


def pipeline_verdicts(model: VerifierModel, items: list[tuple[Example, int]]) -> list[str]:
    """Evidence mode: the source article is retrievable, as in a normal round."""
    out = []
    for ex, _hid in items:
        hits = retrieve(ex.claim, exclude_headline_id=None)
        verdict, _, _ = aggregate(model.score(ex.claim, [h.text for h in hits]))
        out.append(verdict)
    return out


def refute_recall(model: VerifierModel, lies: list[tuple[Example, int]]) -> dict:
    verdicts = pipeline_verdicts(model, lies)
    caught = [float(v == "refuted") for v in verdicts]
    by_type: dict[str, list[float]] = defaultdict(list)
    for (ex, _), c in zip(lies, caught):
        by_type[ex.edit_type or "other"].append(c)
    return {"overall": ci(caught),
            "by_edit_type": {k: ci(v) for k, v in sorted(by_type.items())},
            "verdicts": {lab: verdicts.count(lab) for lab in LABELS}}


def false_positive(model: VerifierModel, truths: list[tuple[Example, int]]) -> dict:
    verdicts = pipeline_verdicts(model, truths)
    return {"overall": ci([float(v == "refuted") for v in verdicts]),
            "verdicts": {lab: verdicts.count(lab) for lab in LABELS}}


def vitaminc_scores(model: VerifierModel, examples: list[Example]) -> dict:
    if not examples:
        return {"accuracy": ci([]), "macro_f1": ci([])}
    preds = []
    for ex in examples:
        p = model.score(ex.claim, [ex.premise])[0]
        preds.append(max(LABELS, key=lambda lab: p[lab]))
    gold = [ex.label for ex in examples]
    correct = [float(a == b) for a, b in zip(preds, gold)]

    idx = np.arange(len(gold))
    rng = np.random.default_rng(SEED)
    g, pr = np.asarray(gold), np.asarray(preds)
    boots = []
    for _ in range(RESAMPLES):
        s = rng.choice(idx, len(idx))
        boots.append(f1_score(g[s], pr[s], labels=list(LABELS), average="macro", zero_division=0))
    f1 = f1_score(gold, preds, labels=list(LABELS), average="macro", zero_division=0)
    return {"accuracy": ci(correct),
            "macro_f1": {"value": round(float(f1), 4), "lo": round(float(np.percentile(boots, 2.5)), 4),
                         "hi": round(float(np.percentile(boots, 97.5)), 4), "n": len(gold)}}


def score_all(model: VerifierModel, sets: dict, vc: list[Example]) -> dict:
    return {
        "held_out_exploits": refute_recall(model, sets["test"]),
        "fresh_exploits": refute_recall(model, sets["fresh"]),
        "true_headlines": false_positive(model, sets["true_test"]),
        "vitaminc": vitaminc_scores(model, vc),
    }

