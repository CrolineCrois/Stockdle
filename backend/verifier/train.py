"""Fine-tune a verifier on (evidence passage, claim, label) examples.

Shared by the evaluation (v1-human / v1-synthetic / v1-combined) and by patch
days, so every compared model is trained with exactly the same settings. The
NLI head is kept: SUPPORTED -> entailment, REFUTED -> contradiction,
NEI -> neutral, so a fine-tuned version is a drop-in for v0.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from app import config

from .model import LABELS, VerifierModel

SETTINGS = {"epochs": 3, "lr": 1e-5, "batch_size": 8, "seed": 7}


@dataclass
class Example:
    premise: str          # an evidence passage
    claim: str            # a headline (true or edited)
    label: str            # supported | refuted | nei
    edit_type: str = ""
    source: str = ""      # human | synthetic | true


def _device() -> torch.device:
    if torch.cuda.is_available():
        return torch.device("cuda")
    if torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def finetune(name: str, init: str | Path, examples: list[Example], out_dir: Path, *,
             epochs: int = SETTINGS["epochs"], lr: float = SETTINGS["lr"],
             batch_size: int = SETTINGS["batch_size"], seed: int = SETTINGS["seed"],
             log=print) -> VerifierModel:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    device = _device()
    tok = AutoTokenizer.from_pretrained(init)
    model = AutoModelForSequenceClassification.from_pretrained(init).to(device)
    id2label = {int(k): str(v).lower() for k, v in model.config.id2label.items()}
    col = {"supported": next(k for k, v in id2label.items() if v == "entailment"),
           "refuted": next(k for k, v in id2label.items() if v == "contradiction"),
           "nei": next(k for k, v in id2label.items() if v in ("neutral", "not_entailment"))}

    counts = {lab: max(1, sum(e.label == lab for e in examples)) for lab in LABELS}
    weight = torch.ones(model.config.num_labels, device=device)
    for lab, c in counts.items():
        weight[col[lab]] = len(examples) / (len(LABELS) * c)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0.01)
    order = list(range(len(examples)))
    for epoch in range(epochs):
        model.train()
        random.shuffle(order)
        total = 0.0
        for i in range(0, len(order), batch_size):
            batch = [examples[j] for j in order[i:i + batch_size]]
            # Pad to multiples of 64 tokens: Apple's MPS backend recompiles for every
            # new tensor shape, so free-length padding made each batch pay a compile.
            enc = tok([e.premise for e in batch], [e.claim for e in batch], truncation="only_first",
                      max_length=config.VERIFIER_MAX_LEN, padding=True, pad_to_multiple_of=64,
                      return_tensors="pt").to(device)
            target = torch.tensor([col[e.label] for e in batch], device=device)
            loss = torch.nn.functional.cross_entropy(model(**enc).logits, target, weight=weight)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            opt.zero_grad()
            total += loss.item() * len(batch)
        log(f"[verifier] {name} epoch {epoch + 1}/{epochs} loss {total / max(1, len(order)):.4f}")
    model.to("cpu").eval()
    out_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(out_dir)
    tok.save_pretrained(out_dir)
    return VerifierModel(name, out_dir)
