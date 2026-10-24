"""What every detector version provides."""

from __future__ import annotations

from typing import Protocol


class Detector(Protocol):
    name: str      # version name, e.g. "stub", "v0", "v1"
    kind: str      # "baseline" | "distilbert"

    def predict(self, pairs: list[tuple[str, str]]) -> list[float]:
        """P(false) for each (headline, snippet) pair."""
        ...


def predict_one(detector: Detector, headline: str, snippet: str) -> float:
    return float(detector.predict([(headline, snippet)])[0])
