"""Claim -> retrieved passages -> one verdict, with the evidence it used."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from app import config

from . import registry
from .model import VerifierModel, aggregate
from .retrieval import retrieve

EVIDENCE, BREAKING = "evidence", "breaking"


@dataclass
class Evidence:
    passage_id: int
    headline_id: int
    text: str
    retrieval_score: float
    probs: dict[str, float]
    decisive: bool = False


@dataclass
class Verification:
    verdict: str                       # supported | refuted | nei
    probs: dict[str, float]            # of the deciding passage (or the strongest, for nei)
    version: str
    mode: str
    passages: list[Evidence] = field(default_factory=list)

    @property
    def passage_ids(self) -> list[int]:
        return [p.passage_id for p in self.passages]

    def to_dict(self) -> dict:
        return asdict(self)


def verify(claim: str, source_headline_id: int, mode: str = EVIDENCE,
           model: VerifierModel | None = None, k: int | None = None) -> Verification:
    """Check ``claim`` against the corpus. Breaking-news mode hides its own source."""
    model = model or registry.current()
    hits = retrieve(claim, k or config.VERIFIER_TOP_K,
                    exclude_headline_id=source_headline_id if mode == BREAKING else None)
    per = model.score(claim, [h.text for h in hits])
    verdict, probs, decisive = aggregate(per)
    passages = [Evidence(h.passage_id, h.headline_id, h.text, h.score, p, i == decisive)
                for i, (h, p) in enumerate(zip(hits, per))]
    return Verification(verdict, probs, model.name, mode, passages)
