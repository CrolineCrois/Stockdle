"""Phase-1 stub detector: logistic regression on headline-vs-snippet features.

The features ask one question in several ways: what does the headline claim
that the snippet does not back up? Numbers, names, negations and reversed
words that appear in the headline but not the snippet are the usual tells of
a small factual edit. It is crude and quick (well under a millisecond), which
is exactly what a stub needs to be; phase 2 replaces it with DistilBERT.
"""

from __future__ import annotations

import re
from pathlib import Path

import joblib
import numpy as np
from sklearn.feature_extraction import DictVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

from app.diffing import norm
from app.lexicon import ANTONYMS, NEGATIONS, is_entity, is_number

FUNCTION = {"a", "an", "the", "of", "to", "in", "on", "for", "and", "as", "at", "by", "with",
            "is", "are", "was", "be", "its", "it", "this", "that", "from", "after", "says",
            "over", "into", "amid", "has", "have", "will", "new"}
_DIGITS = re.compile(r"\d+(?:[.,]\d+)*")


def features(headline: str, snippet: str) -> dict[str, float]:
    raw = headline.split()
    words = [norm(w) for w in raw]
    snip = {norm(w) for w in snippet.split()}
    snip_digits = set(_DIGITS.findall(snippet.replace(",", "")))
    content = [w for w in words if w and w not in FUNCTION]
    unsupported = [w for w in content if w not in snip]

    f: dict[str, float] = {
        "bias": 1.0,
        "frac_unsupported": len(unsupported) / max(1, len(content)),
        "n_unsupported": float(len(unsupported)),
        "numbers_unsupported": float(sum(
            1 for d in _DIGITS.findall(headline.replace(",", "")) if d not in snip_digits)),
        "numbers_in_headline": float(sum(1 for w in raw if is_number(w.strip(".,:;'\"")))),
        "entities_unsupported": float(sum(
            1 for w, n in zip(raw[1:], words[1:]) if is_entity(w.strip(".,:;'\"")) and n not in snip)),
        "negation_unsupported": float(sum(1 for w in words if w in NEGATIONS and w not in snip)),
        "antonym_of_snippet": float(sum(
            1 for w in words if w in ANTONYMS and w not in snip and ANTONYMS[w] in snip)),
        "headline_len": len(words) / 20.0,
    }
    # The unsupported words themselves, so it can learn that "not" or "denies"
    # appearing out of nowhere is worse than a paraphrase.
    for w in unsupported:
        f[f"u={w}"] = 1.0
    return f


class BaselineDetector:
    kind = "baseline"

    def __init__(self, name: str, pipeline: Pipeline) -> None:
        self.name = name
        self.pipeline = pipeline

    def predict(self, pairs: list[tuple[str, str]]) -> list[float]:
        X = [features(h, s) for h, s in pairs]
        return [float(p) for p in self.pipeline.predict_proba(X)[:, 1]]

    @classmethod
    def train(cls, name: str, pairs: list[tuple[str, str]], labels: list[int]) -> "BaselineDetector":
        pipe = Pipeline([
            ("vec", DictVectorizer(sparse=True)),
            ("lr", LogisticRegression(C=0.5, max_iter=2000, class_weight="balanced")),
        ])
        pipe.fit([features(h, s) for h, s in pairs], np.asarray(labels))
        return cls(name, pipe)

    def save(self, directory: Path) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "model.joblib"
        joblib.dump(self.pipeline, path)
        return path

    @classmethod
    def load(cls, name: str, directory: Path) -> "BaselineDetector":
        return cls(name, joblib.load(Path(directory) / "model.joblib"))
