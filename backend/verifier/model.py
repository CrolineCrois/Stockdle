"""The 3-way verification model: P(SUPPORTED / REFUTED / NOT ENOUGH INFO).

The base is an NLI model trained on MNLI, FEVER and ANLI, so its labels map
directly: entailment -> SUPPORTED, contradiction -> REFUTED, neutral -> NEI.
Input is (passage, claim) -- premise first. Each retrieved passage is scored
separately; ``aggregate`` turns those into one verdict.
"""

from __future__ import annotations

from pathlib import Path

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from app import config

LABELS = ("supported", "refuted", "nei")
_NLI_TO_OURS = {"entailment": "supported", "contradiction": "refuted", "neutral": "nei",
                "not_entailment": "nei"}


class VerifierModel:
    def __init__(self, name: str, source: str | Path) -> None:
        self.name = name
        self.tokenizer = AutoTokenizer.from_pretrained(source)
        self.model = AutoModelForSequenceClassification.from_pretrained(source).eval()
        id2label = {int(k): str(v).lower() for k, v in self.model.config.id2label.items()}
        self.column = {_NLI_TO_OURS[v]: k for k, v in id2label.items() if v in _NLI_TO_OURS}
        missing = set(LABELS) - set(self.column)
        if missing:
            raise ValueError(f"{source}: no label for {missing} in {id2label}")

    @torch.inference_mode()
    def score(self, claim: str, passages: list[str]) -> list[dict[str, float]]:
        if not passages:
            return []
        enc = self.tokenizer(passages, [claim] * len(passages), truncation="only_first",
                             max_length=config.VERIFIER_MAX_LEN, padding=True, return_tensors="pt")
        probs = torch.softmax(self.model(**enc).logits, dim=-1)
        return [{lab: round(float(p[self.column[lab]]), 4) for lab in LABELS} for p in probs]

    def save(self, directory: Path) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        self.model.save_pretrained(directory)
        self.tokenizer.save_pretrained(directory)
        return directory


def aggregate(per_passage: list[dict[str, float]], decide_at: float | None = None, *,
              passage_sources: list[int] | None = None, source: int | None = None,
              rule: str | None = None):
    """One verdict from per-passage probabilities.

    A claim is REFUTED if any passage contradicts it confidently (and more
    strongly than any passage supports it); SUPPORTED if a passage confidently
    supports it; otherwise NOT ENOUGH INFO. Returns (verdict, probs, index of
    the deciding passage or None).

    With rule "source" (config.VERIFIER_RULE), a confident contradiction from a
    passage of the claim's own source article (``passage_sources[i] == source``)
    is REFUTED even if another passage supports the claim more strongly.
    """
    t = config.VERIFIER_DECIDE_AT if decide_at is None else decide_at
    if not per_passage:
        return "nei", {"supported": 0.0, "refuted": 0.0, "nei": 1.0}, None
    r_i = max(range(len(per_passage)), key=lambda i: per_passage[i]["refuted"])
    s_i = max(range(len(per_passage)), key=lambda i: per_passage[i]["supported"])
    r, s = per_passage[r_i]["refuted"], per_passage[s_i]["supported"]
    if r >= t and r >= s:
        return "refuted", per_passage[r_i], r_i
    if (rule or config.VERIFIER_RULE) == "source" and passage_sources and source is not None:
        own = [i for i, h in enumerate(passage_sources) if h == source and per_passage[i]["refuted"] >= t]
        if own:
            i = max(own, key=lambda i: per_passage[i]["refuted"])
            return "refuted", per_passage[i], i
    if s >= t:
        return "supported", per_passage[s_i], s_i
    best = max(range(len(per_passage)), key=lambda i: max(per_passage[i]["supported"],
                                                           per_passage[i]["refuted"]))
    return "nei", per_passage[best], None
