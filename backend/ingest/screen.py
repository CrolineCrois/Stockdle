"""Screen headlines for game material: is there a checkable fact to twist?

    python -m ingest.screen            # unscreened headlines only
    python -m ingest.screen --all      # everything again

Feature and opinion headlines ("German 'lawfare': When lawsuits become a
political weapon", "The hidden cost of the night shift…") state nothing a
1-3 word edit can make false -- edits come out either still true or
nonsense. An LLM rates each headline once, in batches; failures are dealt
only when nothing else is left (never deleted).
"""

from __future__ import annotations

import argparse
import json

from sqlalchemy import select

from app import config
from app.db import SessionLocal, init_db
from app.models import Headline

BATCH = 25
PROMPT = """For each news headline below, decide whether it is good material for a game \
where players change 1-3 words to make the headline FALSE while it still reads as a \
believable headline.

Good (checkable = true): it states a concrete fact -- who did what, a number, an outcome, \
a place, a date, a cause -- that a small edit could flip into a falsehood. \
Example: "135 arrested as marches held under tight security".

Bad (checkable = false): feature, explainer, opinion, analysis, lifestyle or question \
headlines with no specific factual claim. Examples: "When lawsuits become a political \
weapon", "The hidden cost of the night shift and how to sleep it off".

reason: at most 12 words.

Headlines:
{items}"""

SCHEMA = {
    "type": "object",
    "properties": {"ratings": {"type": "array", "items": {
        "type": "object",
        "properties": {"id": {"type": "integer"}, "checkable": {"type": "boolean"},
                       "reason": {"type": "string"}},
        "required": ["id", "checkable", "reason"], "additionalProperties": False}}},
    "required": ["ratings"], "additionalProperties": False,
}


def _ask(batch: list[Headline]) -> list[dict]:
    from evaluation.data import pick_provider
    items = "\n".join(f'{h.id}. "{h.text}"' for h in batch)
    prompt = PROMPT.format(items=items)
    if pick_provider() == "openai":
        import openai
        r = openai.OpenAI(max_retries=3).chat.completions.create(
            model=config.OPENAI_JUDGE_MODEL, max_completion_tokens=4000,
            response_format={"type": "json_schema", "json_schema": {
                "name": "ratings", "strict": True, "schema": SCHEMA}},
            messages=[{"role": "user", "content": prompt}])
        text = r.choices[0].message.content or "{}"
    else:
        import anthropic
        r = anthropic.Anthropic(max_retries=3).beta.messages.create(
            model=config.JUDGE_MODEL, max_tokens=4000,
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
            betas=["server-side-fallback-2026-07-01"], fallbacks="default",
            messages=[{"role": "user", "content": prompt}])
        text = next((b.text for b in r.content if b.type == "text"), "{}")
    try:
        return json.loads(text)["ratings"]
    except (json.JSONDecodeError, KeyError):
        return []


def run(all_: bool = False) -> dict:
    init_db()
    with SessionLocal() as db:
        q = select(Headline).where(Headline.active)
        if not all_:
            q = q.where(Headline.checkable.is_(None))
        heads = list(db.scalars(q).all())
        by_id = {h.id: h for h in heads}
        done = bad = 0
        for i in range(0, len(heads), BATCH):
            for r in _ask(heads[i:i + BATCH]):
                h = by_id.get(r.get("id"))
                if h is None:
                    continue
                h.checkable, h.checkable_reason = bool(r["checkable"]), str(r["reason"])[:200]
                done += 1
                bad += not h.checkable
            db.commit()
            print(f"[screen] {min(i + BATCH, len(heads))}/{len(heads)}")
    return {"screened": done, "not_checkable": bad}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    print(f"[screen] {run(all_=ap.parse_args().all)}")


if __name__ == "__main__":
    main()
