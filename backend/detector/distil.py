"""The real detector: DistilBERT fine-tuned as a sentence-pair classifier.

Input is the pair (headline, article snippet) -- the snippet is truncated
first, the headline never is -- and the output is P(false). Inference runs on
CPU for predictable latency (~10-30 ms per call on a laptop, fine for a
debounced meter); training uses Apple's MPS or CUDA when available.

``finetune`` is shared by v0 (from the pretrained base) and every patch day
(from the previous version), so all versions are trained the same way.
"""

from __future__ import annotations

import random
from pathlib import Path

import numpy as np
import torch
from torch.nn.functional import softmax
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from app import config

torch.set_num_threads(max(1, min(4, torch.get_num_threads())))


def train_device() -> torch.device:
    if torch.cuda.is_available():
        return torch.device("cuda")
    if torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


class DistilDetector:
    kind = "distilbert"

    def __init__(self, name: str, tokenizer, model) -> None:
        self.name = name
        self.tokenizer = tokenizer
        self.model = model.eval().to("cpu")

    @classmethod
    def load(cls, name: str, directory: Path) -> "DistilDetector":
        directory = Path(directory)
        return cls(name, AutoTokenizer.from_pretrained(directory),
                   AutoModelForSequenceClassification.from_pretrained(directory))

    def _encode(self, pairs: list[tuple[str, str]]):
        return self.tokenizer([h for h, _ in pairs], [s or "" for _, s in pairs],
                              truncation="only_second", max_length=config.DETECTOR_MAX_LEN,
                              padding=True, return_tensors="pt")

    @torch.inference_mode()
    def predict(self, pairs: list[tuple[str, str]], batch_size: int = 64) -> list[float]:
        out: list[float] = []
        for i in range(0, len(pairs), batch_size):
            logits = self.model(**self._encode(pairs[i:i + batch_size])).logits
            out += softmax(logits, dim=-1)[:, 1].tolist()
        return out

    def save(self, directory: Path) -> Path:
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        self.model.save_pretrained(directory)
        self.tokenizer.save_pretrained(directory)
        return directory


def finetune(name: str, init: str | Path, pairs: list[tuple[str, str]], labels: list[int], *,
             epochs: int = 10, lr: float = 5e-5, batch_size: int = 16, seed: int = 7,
             log=print) -> DistilDetector:
    """Fine-tune from ``init`` (a hub id or a saved version's directory)."""
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    device = train_device()
    tokenizer = AutoTokenizer.from_pretrained(init)
    model = AutoModelForSequenceClassification.from_pretrained(init, num_labels=2).to(device)

    # Balance the classes: a patch day can be heavily skewed toward one label.
    y = np.asarray(labels)
    pos = max(1, int(y.sum()))
    neg = max(1, len(y) - pos)
    weight = torch.tensor([len(y) / (2 * neg), len(y) / (2 * pos)], dtype=torch.float, device=device)
    loss_fn = torch.nn.CrossEntropyLoss(weight=weight)

    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0.01)
    steps = epochs * ((len(pairs) + batch_size - 1) // batch_size)
    sched = torch.optim.lr_scheduler.LambdaLR(
        opt, lambda s: min(1.0, (s + 1) / max(1, steps // 10)) * max(0.0, 1 - s / steps))

    order = list(range(len(pairs)))
    model.train()
    for epoch in range(epochs):
        random.shuffle(order)
        total = 0.0
        for i in range(0, len(order), batch_size):
            idx = order[i:i + batch_size]
            enc = tokenizer([pairs[j][0] for j in idx], [pairs[j][1] or "" for j in idx],
                            truncation="only_second", max_length=config.DETECTOR_MAX_LEN,
                            padding=True, return_tensors="pt").to(device)
            target = torch.tensor([labels[j] for j in idx], device=device)
            loss = loss_fn(model(**enc).logits, target)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            sched.step()
            opt.zero_grad()
            total += loss.item() * len(idx)
        log(f"[train] {name} epoch {epoch + 1}/{epochs} loss {total / len(order):.4f}")
    return DistilDetector(name, tokenizer, model.to("cpu"))
