"""Generate false variants of true headlines: the v0 detector's training fakes.

    python -m ingest.make_fakes              # Claude if a key is set, else rules
    python -m ingest.make_fakes --rules      # force the rule-based generator
    python -m ingest.make_fakes --per 2      # fakes per headline (default 2)

With an API key, Claude makes small factual edits (1-3 words) in batches,
returned as strict JSON. Every fake is then held to the same rule players are:
the word-level diff must be 1-3 changes, or it is discarded. Headlines that
already have fakes from the same generator are skipped, so re-running only
fills gaps.

This is the baseline the game is built to beat: a detector that has only ever
seen *LLM-made* lies. Human players then find the blind spots it has.
"""

from __future__ import annotations

import argparse
import json
import os
import random

from sqlalchemy import select

from app import config
from app.db import SessionLocal, init_db
from app.diffing import word_diff
from app.models import Headline, SyntheticFake
from judge.base import EDIT_TYPES

from .perturb import entity_pool, make_fakes as rule_fakes

BATCH = 20

PROMPT = """You are generating training data for a misinformation detector in a \
research game. For each TRUE news headline below (with a snippet of its article), \
write {per} different FALSE version(s) of it.

Rules for every false version:
- Change between 1 and 3 words of the original (substitute, insert or delete). \
Keep every other word exactly as it is.
- It must now state something the snippet contradicts or does not support: a wrong \
number, a reversed outcome, the wrong person, place or organisation, an invented \
cause, a negation.
- It must still read as a plausible, grammatical news headline.
- Vary the kind of edit across the batch.

Headlines:
{items}"""

SCHEMA = {
    "type": "object",
    "properties": {
        "fakes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "fake": {"type": "string"},
                    "edit_type": {"type": "string", "enum": list(EDIT_TYPES)},
                },
                "required": ["id", "fake", "edit_type"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["fakes"],
    "additionalProperties": False,
}


def _claude_batch(client, batch: list[Headline], per: int) -> list[dict]:
    import anthropic

    items = "\n".join(f'{h.id}. "{h.text}"\n   Snippet: {h.snippet[:300]}' for h in batch)
    try:
        response = client.beta.messages.create(
            model=config.FAKES_MODEL,
            max_tokens=16000,
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            messages=[{"role": "user", "content": PROMPT.format(per=per, items=items)}],
        )
    except anthropic.APIError as exc:
        print(f"[fakes] batch failed: {type(exc).__name__}: {exc}")
        return []
    if response.stop_reason == "refusal":
        print("[fakes] batch refused; skipping it")
        return []
    text = next((b.text for b in response.content if b.type == "text"), "")
    try:
        return json.loads(text)["fakes"]
    except (json.JSONDecodeError, KeyError) as exc:
        print(f"[fakes] malformed batch output: {exc}")
        return []


def generate(*, use_rules: bool, per: int = 2, seed: int = 11) -> dict:
    init_db()
    use_claude = not use_rules and bool(os.environ.get("ANTHROPIC_API_KEY"))
    generator = "claude" if use_claude else "rules"
    with SessionLocal() as db:
        heads = list(db.scalars(select(Headline).where(Headline.active)).all())
        done = set(db.scalars(select(SyntheticFake.headline_id)
                              .where(SyntheticFake.generator == generator)).all())
        todo = [h for h in heads if h.id not in done]
        by_id = {h.id: h for h in heads}
        kept = dropped = 0

        if use_claude:
            import anthropic
            client = anthropic.Anthropic(max_retries=3)
            for i in range(0, len(todo), BATCH):
                for item in _claude_batch(client, todo[i:i + BATCH], per):
                    h = by_id.get(item.get("id"))
                    fake = " ".join(str(item.get("fake", "")).split())
                    n = word_diff(h.text, fake).num_changes if h else 0
                    if h is None or not 1 <= n <= config.MAX_WORD_CHANGES:
                        dropped += 1
                        continue
                    db.add(SyntheticFake(headline_id=h.id, text=fake, edit_type=item["edit_type"],
                                         generator="claude", model=config.FAKES_MODEL))
                    kept += 1
                db.commit()
                print(f"[fakes] {min(i + BATCH, len(todo))}/{len(todo)} headlines")
        else:
            rng = random.Random(seed)
            pool = entity_pool([h.text for h in heads])
            for h in todo:
                for fake, kind in rule_fakes(h.text, pool, rng, max_fakes=per):
                    db.add(SyntheticFake(headline_id=h.id, text=fake, edit_type=kind,
                                         generator="rules"))
                    kept += 1
            db.commit()
    return {"generator": generator, "headlines": len(todo), "kept": kept, "dropped": dropped}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rules", action="store_true", help="use the rule-based generator")
    ap.add_argument("--per", type=int, default=2, help="fakes per headline")
    args = ap.parse_args()
    summary = generate(use_rules=args.rules, per=args.per)
    print(f"[fakes] {summary}")
    if summary["generator"] == "rules" and not args.rules:
        print("[fakes] no ANTHROPIC_API_KEY: used rule-based fakes. Set a key and re-run "
              "for the LLM-made fakes the v0 baseline is meant to use.")


if __name__ == "__main__":
    main()
