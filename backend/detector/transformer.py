"""The real detector: a small transformer that reads (article snippet, headline).

Default base: ``cross-encoder/nli-deberta-v3-xsmall`` (71M parameters, ~12 ms
per call on a laptop CPU). It is an NLI cross-encoder -- already trained to say
whether a premise supports or contradicts a claim -- which is this task exactly:
premise = the snippet, claim = the headline. With only a few hundred training
examples that head start matters: a plain DistilBERT fine-tuned on the same
data stayed at chance on LLM-written fakes (held-out AUC ~0.55); the NLI model
reaches ~0.75. See PROGRESS.md.

Two modes, picked from the base model's labels:

    nli         labels include entailment/contradiction. Input (snippet, headline);
                score = P(contradiction) / (P(contradiction) + P(entailment));
                training pushes true -> entailment, false -> contradiction.
    classifier  a plain 2-label head (e.g. distilbert-base-uncased).
                Input (headline, snippet); score = P(label 1).

Calibration. Raw scores are a ranking, not a probability the game can use
directly: the NLI model rates most short-snippet headlines as "not entailed",
so at a raw 0.5 it flags half of all true headlines. Each version therefore
stores a ``threshold`` (chosen on validation headlines so ~20% of true
headlines are flagged) and reports scores remapped so that threshold sits at
0.5 -- the meter's line. The remap is monotone, so rankings and AUC are
unchanged.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import numpy as np
import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from app import config

torch.set_num_threads(max(1, min(4, torch.get_num_threads())))
CALIBRATION_FILE = "calibration.json"
TARGET_FALSE_ALARM = 0.2


def train_device() -> torch.device:
    if torch.cuda.is_available():
        return torch.device("cuda")
    if torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def _nli_ids(model) -> tuple[int, int] | None:
    labels = {str(v).lower(): int(k) for k, v in model.config.id2label.items()}
    if "entailment" in labels and "contradiction" in labels:
        return labels["entailment"], labels["contradiction"]
    return None


def calibrate(raw: float, threshold: float) -> float:
    """Monotone remap putting ``threshold`` at 0.5."""
    t = min(max(threshold, 1e-6), 1 - 1e-6)
    return 0.5 * raw / t if raw < t else 0.5 + 0.5 * (raw - t) / (1 - t)


class TransformerDetector:
    kind = "transformer"

    def __init__(self, name: str, tokenizer, model, threshold: float = 0.5) -> None:
        self.name = name
        self.tokenizer = tokenizer
        self.model = model.eval().to("cpu")
        self.nli = _nli_ids(model)
        self.threshold = threshold

    @classmethod
    def load(cls, name: str, directory: Path) -> "TransformerDetector":
        directory = Path(directory)
        cal = directory / CALIBRATION_FILE
        threshold = json.loads(cal.read_text())["threshold"] if cal.exists() else 0.5
        return cls(name, AutoTokenizer.from_pretrained(directory),
                   AutoModelForSequenceClassification.from_pretrained(directory), threshold)

    def save(self, directory: Path) -> Path:
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        self.model.save_pretrained(directory)
        self.tokenizer.save_pretrained(directory)
        (directory / CALIBRATION_FILE).write_text(json.dumps({"threshold": self.threshold}))
        return directory

    @torch.inference_mode()
    def raw_scores(self, pairs: list[tuple[str, str]], batch_size: int = 64) -> list[float]:
        out: list[float] = []
        for i in range(0, len(pairs), batch_size):
            batch = pairs[i:i + batch_size]
            logits = self.model(**_encode(self.tokenizer, batch, self.nli is not None)).logits
            out += _score(logits, self.nli).tolist()
        return out

    def predict(self, pairs: list[tuple[str, str]]) -> list[float]:
        return [calibrate(r, self.threshold) for r in self.raw_scores(pairs)]

    def fit_threshold(self, true_pairs: list[tuple[str, str]],
                      target: float = TARGET_FALSE_ALARM) -> float:
        """Pick the raw score above which ``target`` of these true headlines fall."""
        raw = np.asarray(self.raw_scores(true_pairs))
        if raw.size:
            self.threshold = float(np.quantile(raw, 1 - target))
        return self.threshold


def _encode(tokenizer, pairs, nli: bool):
    if nli:   # premise = snippet, hypothesis = headline; never truncate the headline
        return tokenizer([s or "" for _, s in pairs], [h for h, _ in pairs],
                         truncation="only_first", max_length=config.DETECTOR_MAX_LEN,
                         padding=True, return_tensors="pt")
    return tokenizer([h for h, _ in pairs], [s or "" for _, s in pairs],
                     truncation="only_second", max_length=config.DETECTOR_MAX_LEN,
                     padding=True, return_tensors="pt")


def _two_way(logits, nli):
    """Logits as [true, false] columns, whichever head the model has."""
    if nli:
        ent, con = nli
        return torch.stack([logits[:, ent], logits[:, con]], dim=1)
    return logits


def _score(logits, nli):
    return torch.softmax(_two_way(logits, nli), dim=-1)[:, 1]


def finetune(name: str, init: str | Path, pairs: list[tuple[str, str]], labels: list[int], *,
             epochs: int = 4, lr: float = 2e-5, batch_size: int = 8, seed: int = 7,
             log=print) -> TransformerDetector:
    """Fine-tune from ``init`` (a hub id or a saved version's directory)."""
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    device = train_device()
    tokenizer = AutoTokenizer.from_pretrained(init)
    model = AutoModelForSequenceClassification.from_pretrained(init)
    nli = _nli_ids(model)
    if nli is None and model.config.num_labels != 2:
        model = AutoModelForSequenceClassification.from_pretrained(
            init, num_labels=2, ignore_mismatched_sizes=True)
    model.to(device)

    # Balance the classes: a patch day can be heavily skewed toward one label.
    y = np.asarray(labels)
    pos = max(1, int(y.sum()))
    neg = max(1, len(y) - pos)
    weight = torch.tensor([len(y) / (2 * neg), len(y) / (2 * pos)], dtype=torch.float, device=device)

    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0.01)
    order = list(range(len(pairs)))
    for epoch in range(epochs):
        model.train()
        random.shuffle(order)
        total = 0.0
        for i in range(0, len(order), batch_size):
            idx = order[i:i + batch_size]
            enc = _encode(tokenizer, [pairs[j] for j in idx], nli is not None).to(device)
            target = torch.tensor([labels[j] for j in idx], device=device)
            loss = torch.nn.functional.cross_entropy(_two_way(model(**enc).logits, nli), target,
                                                     weight=weight)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            opt.zero_grad()
            total += loss.item() * len(idx)
        log(f"[train] {name} epoch {epoch + 1}/{epochs} loss {total / len(order):.4f}")
    return TransformerDetector(name, tokenizer, model.to("cpu"))
