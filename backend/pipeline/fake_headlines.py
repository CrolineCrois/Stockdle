"""Fabricated headlines for the disinformation-detection rounds.

These rounds pair a *real* price chart with a headline that never happened.
The hidden half is the genuine price path, which of course did not react --
so a player who trades the headline overreacts and loses points, and the
reveal shows them exactly that.

Responsible-design rules enforced here and downstream:

* Every fake carries ``is_fake = True`` on both the headline and the round.
* The round's context card renders inside a quarantine frame, and the reveal
  banner always says the headline was fabricated.
* Fake headline *text* is never included in share strings or any export --
  see ``app/schemas.py`` (share payloads carry scores only) and
  ``pipeline/build_rounds.py`` (``export_safe`` strips it).

If ``ANTHROPIC_API_KEY`` is set the fakes are generated with the Claude API for
variety; otherwise the bundled template list below is used.
"""

from __future__ import annotations

import os
import re

from .common import RAW_DIR, log, read_json, write_json

# ~20 templates, deliberately plausible-but-false market-moving claims.
FAKE_TEMPLATES: list[str] = [
    "BREAKING: {name} CEO resigns abruptly amid internal review",
    "{name} halts all shipments after regulator issues emergency ban",
    "Leaked memo: {name} to cut 30% of workforce next quarter",
    "{name} under federal investigation for accounting irregularities",
    "{name} loses landmark patent suit, ordered to pay $4.2B",
    "Exclusive: {name} board votes to explore a sale of the company",
    "{name} data breach exposed 180 million customer records",
    "{name} flagship product recalled worldwide over safety defect",
    "{name} to be removed from major indices after listing review",
    "Rival agrees to acquire {name} at a 45% premium, sources say",
    "{name} CFO sells entire stake days before guidance cut",
    "{name} suspends dividend to fund emergency restructuring",
    "Court freezes {name} assets pending antitrust ruling",
    "{name} warehouse fire destroys a quarter of holiday inventory",
    "Whistleblower alleges {name} inflated subscriber numbers for years",
    "{name} loses its largest customer to a low-cost competitor",
    "Government blocks {name} from bidding on public contracts",
    "{name} to delist from US exchanges, move primary listing overseas",
    "Auditor resigns, citing inability to rely on {name} management",
    "{name} announces surprise 1-for-8 reverse stock split",
]

_LLM_CACHE = RAW_DIR / "fake_headlines_llm.json"

_ANTHROPIC_PROMPT = (
    "Write {n} short, plausible-sounding but entirely FICTIONAL financial news "
    "headlines about a company referred to only as {{name}} (keep the literal "
    "placeholder {{name}} in each headline). They are used in a game that "
    "teaches people to spot fabricated market news, and are always shown to "
    "players labelled as fake. Each headline must be the kind of claim that "
    "would move a stock price. Do not name any real company, person, "
    "regulator, or publication. Return one headline per line, no numbering."
)


def _generate_with_claude(n: int = 20) -> list[str]:
    """Ask Claude for fresh fakes. Returns [] if the key or SDK is missing."""
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        return []
    try:
        import anthropic  # type: ignore
    except Exception:
        log("fake headlines: anthropic SDK not installed, using templates")
        return []
    try:
        client = anthropic.Anthropic(api_key=key)
        resp = client.messages.create(
            model="claude-sonnet-5",
            max_tokens=1200,
            messages=[{"role": "user", "content": _ANTHROPIC_PROMPT.format(n=n)}],
        )
        text = "".join(
            block.text for block in resp.content if getattr(block, "type", "") == "text"
        )
        out = []
        for line in text.splitlines():
            line = re.sub(r"^\s*[-*\d.)\s]+", "", line).strip().strip('"')
            if "{name}" in line and 20 < len(line) < 160:
                out.append(line)
        if out:
            log(f"fake headlines: generated {len(out)} via Claude API")
        return out
    except Exception as exc:  # noqa: BLE001
        log(f"fake headlines: Claude API failed ({type(exc).__name__}), using templates")
        return []


def get_fake_templates(use_llm: bool = True) -> list[str]:
    """Return the fake-headline template pool (LLM-augmented when available)."""
    pool = list(FAKE_TEMPLATES)
    if not use_llm:
        return pool
    cached = read_json(_LLM_CACHE)
    if isinstance(cached, list) and cached:
        return pool + [h for h in cached if isinstance(h, str)]
    generated = _generate_with_claude()
    if generated:
        write_json(_LLM_CACHE, generated)
        return pool + generated
    return pool


def strip_fake_text(obj):
    """Recursively replace fake headline text with a neutral label.

    Used anywhere round data might leave the app (share strings, exports) so
    fabricated text can never travel on its own without the FAKE label.
    """
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in ("headline", "title") and obj.get("is_fake"):
                out[k] = "[fabricated headline withheld]"
            else:
                out[k] = strip_fake_text(v)
        return out
    if isinstance(obj, list):
        return [strip_fake_text(v) for v in obj]
    return obj
