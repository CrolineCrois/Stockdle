"""Check a pasted post: pull out its factual claims, then fact-check each one.

    text -> up to MAX_CLAIMS checkable claims (LLM; opinions and jokes skipped)
         -> evidence per claim: the game's own news passages (BM25) plus, when
            enabled, a few fresh headlines from Google News' public RSS search
         -> the live verifier scores every passage -> one verdict per claim

Deliberately limited:
  * text only -- no URLs are fetched (no scraping of X/Reddit, no SSRF);
  * one RSS request per claim, 4 s timeout, top results only, cached 1 hour;
  * nothing is stored unless the person sends feedback (``save_feedback``).

The verdict is about the claim and the evidence found, never about the post or
its author: "contradicted", "supported" or "not enough evidence".
"""

from __future__ import annotations

import html
import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from urllib.parse import quote_plus

from . import config

MAX_CHARS = 1200
MAX_CLAIMS = 3
FRESH_PER_CLAIM = 4
FRESH_TIMEOUT_S = 4.0
FRESH_CACHE_S = 3600
LOCAL_PER_CLAIM = 3

EXTRACT_PROMPT = """Below is a social-media post (or a headline) someone wants fact-checked.

List up to {n} statements from it. For each, set `factual` to true only if it is a
CHECKABLE FACTUAL CLAIM: a specific statement about events, numbers, people, places
or dates that news coverage could confirm or contradict. Set `factual` to false for
opinions, demands ("X should resign"), predictions, jokes, questions, sarcasm and
claims about hidden motives or cover-ups that no article could settle.
Rewrite each as one standalone sentence (resolve "he", "they", "this" from context;
drop emoji, hashtags and @handles). Put anything you left out, and why, in `note`.

Post:
\"\"\"{text}\"\"\""""

SCHEMA = {
    "type": "object",
    "properties": {
        "claims": {"type": "array", "items": {
            "type": "object",
            "properties": {"claim": {"type": "string"}, "factual": {"type": "boolean"}},
            "required": ["claim", "factual"], "additionalProperties": False}},
        "note": {"type": "string"},
    },
    "required": ["claims", "note"],
    "additionalProperties": False,
}


@dataclass
class Passage:
    text: str
    source: str
    url: str
    kind: str                      # "game" (our corpus) | "fresh" (Google News)
    probs: dict[str, float] = field(default_factory=dict)
    decisive: bool = False


@dataclass
class ClaimResult:
    claim: str
    verdict: str                   # refuted | supported | nei   (from the general checker)
    probs: dict[str, float]
    passages: list[Passage]
    trained_verdict: str = ""      # what the newest game-trained version says, for comparison
    trained_model: str = ""


@dataclass
class CheckResult:
    claims: list[ClaimResult]
    note: str
    model: str
    fresh: bool

    def to_dict(self) -> dict:
        return asdict(self)


# --- 1. claims --------------------------------------------------------------
def _sentences(text: str) -> list[str]:
    """No-API fallback: the first few sentence-like chunks."""
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [p.strip() for p in parts if len(p.split()) >= 5][:MAX_CLAIMS]


def extract_claims(text: str) -> tuple[list[str], str]:
    prompt = EXTRACT_PROMPT.format(n=MAX_CLAIMS, text=text)
    try:
        if os.environ.get("OPENAI_API_KEY") and config.JUDGE != "mock":
            import openai
            r = openai.OpenAI(max_retries=2, timeout=20).chat.completions.create(
                model=config.OPENAI_JUDGE_MODEL, max_completion_tokens=600,
                response_format={"type": "json_schema", "json_schema": {
                    "name": "claims", "strict": True, "schema": SCHEMA}},
                messages=[{"role": "user", "content": prompt}])
            out = json.loads(r.choices[0].message.content or "{}")
        elif os.environ.get("ANTHROPIC_API_KEY") and config.JUDGE != "mock":
            import anthropic
            r = anthropic.Anthropic(max_retries=2).beta.messages.create(
                model=config.JUDGE_MODEL, max_tokens=600,
                output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
                betas=["server-side-fallback-2026-07-01"], fallbacks="default",
                messages=[{"role": "user", "content": prompt}])
            out = json.loads(next((b.text for b in r.content if b.type == "text"), "{}"))
        else:
            return _sentences(text), "claims split by sentence (no LLM configured)"
    except Exception as exc:  # noqa: BLE001 -- fall back rather than fail the check
        return _sentences(text), f"claim extraction failed ({type(exc).__name__}); split by sentence"
    claims, skipped = [], []
    for c in out.get("claims", []):
        text_ = str(c.get("claim", "")).strip() if isinstance(c, dict) else ""
        if text_:
            (claims if c.get("factual") else skipped).append(text_)
    note = str(out.get("note", ""))[:300]
    if skipped:
        note = (note + " " if note else "") + "Not checked (opinion, not a fact): " + "; ".join(skipped)
    return claims[:MAX_CLAIMS], note[:600]


# --- 2. evidence ------------------------------------------------------------
_fresh_cache: dict[str, tuple[float, list[Passage]]] = {}


def fresh_evidence(claim: str) -> list[Passage]:
    """A few current headlines about the claim, from Google News' public RSS search."""
    key = claim.lower().strip()
    hit = _fresh_cache.get(key)
    if hit and time.time() - hit[0] < FRESH_CACHE_S:
        return hit[1]
    import feedparser
    import httpx
    from ingest.scrape_rss import AGENT
    url = ("https://news.google.com/rss/search?q=" + quote_plus(claim[:200])
           + "&hl=en-US&gl=US&ceid=US:en")
    try:
        r = httpx.get(url, timeout=FRESH_TIMEOUT_S, headers={"User-Agent": AGENT},
                      follow_redirects=True)
        r.raise_for_status()
    except httpx.HTTPError:
        return []
    out = []
    for e in feedparser.parse(r.text).entries[:FRESH_PER_CLAIM]:
        title = html.unescape(e.get("title", "")).strip()
        source = getattr(e, "source", {}).get("title", "") if hasattr(e, "source") else ""
        if source and title.endswith(" - " + source):
            title = title[: -len(" - " + source)]
        if title:
            out.append(Passage(text=title, source=source or "Google News", url=e.get("link", ""),
                               kind="fresh"))
    if len(_fresh_cache) > 500:
        _fresh_cache.clear()
    _fresh_cache[key] = (time.time(), out)
    return out


def local_evidence(claim: str) -> list[Passage]:
    from verifier.retrieval import retrieve

    from .db import SessionLocal
    from .models import Headline
    hits = retrieve(claim, LOCAL_PER_CLAIM)
    with SessionLocal() as db:
        heads = {h.id: h for h in db.query(Headline).filter(
            Headline.id.in_([h.headline_id for h in hits])).all()}
    return [Passage(text=h.text, source=getattr(heads.get(h.headline_id), "source", ""),
                    url=getattr(heads.get(h.headline_id), "url", "") or "", kind="game")
            for h in hits]


# --- 3. verdicts ------------------------------------------------------------
def check(text: str, *, fresh: bool | None = None, scorer=None) -> CheckResult:
    """The verdict comes from the general-purpose checker (config.CHECK_MODEL,
    default v0). Game-trained versions are specialists in headline edits: they
    were never trained on "not enough info" and treat any related article as
    support, so on outside text they are shown as a second opinion only."""
    from verifier import registry
    from verifier.model import aggregate
    text = text.strip()[:MAX_CHARS]
    fresh = config.CHECK_FRESH if fresh is None else fresh
    model = None if scorer else registry.load(config.CHECK_MODEL)
    trained = None if scorer else registry.current()
    if trained is not None and trained.name == getattr(model, "name", None):
        trained = None
    score = scorer or model.score
    claims, note = extract_claims(text)
    results = []
    for claim in claims:
        passages = local_evidence(claim) + (fresh_evidence(claim) if fresh else [])
        per = score(claim, [p.text for p in passages]) if passages else []
        for p, pr in zip(passages, per):
            p.probs = pr
        # No "source article" here, so the plain rule: the strongest contradiction
        # must beat the strongest support.
        verdict, probs, i = aggregate(per, rule="strongest")
        if i is not None:
            passages[i].decisive = True
        second = ""
        if trained is not None and passages:
            second = aggregate(trained.score(claim, [p.text for p in passages]), rule="strongest")[0]
        results.append(ClaimResult(claim, verdict, probs, passages, second,
                                   trained.name if trained else ""))
    return CheckResult(results, note, getattr(model, "name", "test"), bool(fresh))


def save_feedback(db, *, text: str, result: dict, feedback: str, note: str = "",
                  player_id: str | None = None):
    from .models import CheckFeedback
    row = CheckFeedback(text=text[:MAX_CHARS], result_json=json.dumps(result)[:20000],
                        feedback=feedback, note=note[:300], player_id=player_id or "")
    db.add(row)
    db.commit()
    return row
