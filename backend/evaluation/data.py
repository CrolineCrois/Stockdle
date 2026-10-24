"""Every dataset the evaluation uses, built the same way every time.

Split. Headlines (not exploits) are split ~70/30 into train/test with a fixed
seed, so no headline appears on both sides. Assignments are saved to
``data/eval/split.json`` and only ever extended, so results are reproducible
and a headline never moves between sides. The test side's headlines, unedited,
are the held-out TRUE set (false-positive check). Exploits made after the most
recent patch day are the "fresh" set.

Examples. Each exploit becomes a contrastive pair on the same evidence: the
passage from the source article that best matches the original headline, with
the original labelled SUPPORTED and the edit labelled REFUTED.

Synthetic control. For the same training headlines, an LLM writes minimal,
material, specific false edits, matched to the human training set's edit_type
counts, and every one goes through the same judge filters as a player's.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
from collections import Counter
from datetime import datetime

from sqlalchemy import select

from app import config
from app.db import SessionLocal
from app.diffing import word_diff
from app.models import Attempt, Headline, Passage, SyntheticFake
from verifier.retrieval import tokens
from verifier.train import Example

EVAL_DIR = config.DATA_DIR / "eval"
SPLIT_FILE = EVAL_DIR / "split.json"
SEED = 13
TEST_FRACTION = 0.3


# --- split -------------------------------------------------------------------
def _side(headline_id: int, seed: int) -> str:
    h = int(hashlib.sha1(f"eval-{seed}-{headline_id}".encode()).hexdigest()[:8], 16)
    return "test" if (h % 1000) < TEST_FRACTION * 1000 else "train"


def load_split(headline_ids: list[int]) -> dict:
    saved = json.loads(SPLIT_FILE.read_text()) if SPLIT_FILE.exists() else {
        "seed": SEED, "test_fraction": TEST_FRACTION, "sides": {}, "patch_day_at": None}
    sides = saved["sides"]
    for hid in headline_ids:
        sides.setdefault(str(hid), _side(hid, saved["seed"]))
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    SPLIT_FILE.write_text(json.dumps(saved, indent=1))
    return saved


def mark_patch_day(when: datetime) -> None:
    """Exploits created after this are the 'fresh' test set."""
    saved = json.loads(SPLIT_FILE.read_text()) if SPLIT_FILE.exists() else load_split([])
    saved["patch_day_at"] = when.isoformat()
    SPLIT_FILE.write_text(json.dumps(saved, indent=1))


# --- evidence ------------------------------------------------------------------
def source_premise(db, headline: Headline) -> str:
    """The source passage that best matches the original headline."""
    passages = db.scalars(select(Passage).where(Passage.headline_id == headline.id)).all()
    if not passages:
        return headline.snippet or headline.text
    q = set(tokens(headline.text))
    return max(passages, key=lambda p: (len(q & set(tokens(p.text))), -p.idx)).text


# --- human data ----------------------------------------------------------------
def exploits(db, include_pending: bool = False) -> list[tuple[Attempt, Headline]]:
    """Approved exploits (snuck or partial). ``include_pending`` is for dev runs only."""
    ok = ("approved", "pending", "") if include_pending else ("approved",)
    rows = db.execute(select(Attempt, Headline).join(Headline, Headline.id == Attempt.headline_id)
                      .where(Attempt.outcome.in_(("snuck", "partial")),
                             Attempt.review_status.in_(ok))).all()
    return [(a, h) for a, h in rows]


def human_sets(include_pending: bool = False) -> dict:
    with SessionLocal() as db:
        heads = list(db.scalars(select(Headline).where(Headline.active)).all())
        split = load_split([h.id for h in heads])
        sides = split["sides"]
        fresh_after = datetime.fromisoformat(split["patch_day_at"]) if split["patch_day_at"] else None
        rows = exploits(db, include_pending)
        out = {"train": [], "test": [], "fresh": [], "true_test": []}
        # Stamp each exploit's evaluation side onto its log row.
        for a, h in rows:
            a.split = ("fresh" if fresh_after and a.created_at > fresh_after
                       else sides.get(str(h.id), "train"))
        db.commit()
        premises: dict[int, str] = {}
        for a, h in rows:
            premise = premises.setdefault(h.id, source_premise(db, h))
            ex = Example(premise, a.edited_headline, "refuted", a.edit_type or "other", "human")
            if fresh_after and a.created_at > fresh_after:
                out["fresh"].append((ex, h.id))
            else:
                out[sides.get(str(h.id), "train")].append((ex, h.id))
        for h in heads:
            if sides.get(str(h.id)) == "test":
                out["true_test"].append((Example(premises.setdefault(h.id, source_premise(db, h)),
                                                 h.text, "supported", "", "true"), h.id))
        train_heads = {hid for _, hid in out["train"]}
        out["train_true"] = [Example(premises[hid], next(h.text for h in heads if h.id == hid),
                                     "supported", "", "true") for hid in sorted(train_heads)]
        out["split"] = {"seed": split["seed"], "test_fraction": split["test_fraction"],
                        "patch_day_at": split["patch_day_at"],
                        "train_headlines": len(train_heads),
                        "test_headlines": sum(1 for v in sides.values() if v == "test")}
        return out


# --- synthetic control ---------------------------------------------------------
CONTROL_PROMPT = """You are generating training data for a fact-checking model. For each \
TRUE headline below, write ONE false version using the requested kind of edit.

Rules:
- Change between 1 and 3 words; keep every other word exactly.
- It must be materially false: a reader would believe something meaningful and wrong.
- Keep it as specific as the original: no hedges ("may", "reportedly"), no vague \
quantities ("many", "narrowly"), no unnamed sources.
- It must read as a plausible, grammatical headline.

Edit kinds: number, role swap (who did what to whom reversed), causal (cause or \
consequence invented/reversed), temporal (when or order), negation, quantifier \
(all/some/none), entity swap, other.

Headlines:
{items}"""

CONTROL_SCHEMA = {
    "type": "object",
    "properties": {"edits": {"type": "array", "items": {
        "type": "object",
        "properties": {"id": {"type": "integer"}, "fake": {"type": "string"}},
        "required": ["id", "fake"], "additionalProperties": False}}},
    "required": ["edits"], "additionalProperties": False,
}


def _ask_control(provider: str, batch: list[tuple[int, Headline, str]]) -> dict[int, str]:
    items = "\n".join(f'{i}. [{kind}] "{h.text}"\n   Snippet: {h.snippet[:240]}' for i, h, kind in batch)
    prompt = CONTROL_PROMPT.format(items=items)
    if provider == "openai":
        import openai
        r = openai.OpenAI(max_retries=3).chat.completions.create(
            model=config.OPENAI_FAKES_MODEL, max_completion_tokens=4000,
            response_format={"type": "json_schema", "json_schema": {
                "name": "edits", "strict": True, "schema": CONTROL_SCHEMA}},
            messages=[{"role": "user", "content": prompt}])
        text = r.choices[0].message.content or "{}"
    else:
        import anthropic
        r = anthropic.Anthropic(max_retries=3).beta.messages.create(
            model=config.FAKES_MODEL, max_tokens=8000,
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": CONTROL_SCHEMA}},
            betas=["server-side-fallback-2026-07-01"], fallbacks="default",
            messages=[{"role": "user", "content": prompt}])
        text = next((b.text for b in r.content if b.type == "text"), "{}")
    try:
        return {int(e["id"]): str(e["fake"]) for e in json.loads(text)["edits"]}
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return {}


def synthetic_control(train_human: list[tuple[Example, int]], provider: str,
                      log=print) -> list[Example]:
    """LLM edits of the SAME training headlines, matched to the human edit_type
    counts and filtered by the same judge. Cached in ``synthetic_fakes``
    (generator "<provider>-control"), so re-runs only fill gaps."""
    from judge import get_judge, judge_twice

    generator = f"{provider}-control"
    want = Counter(ex.edit_type for ex, _ in train_human)
    head_ids = sorted({hid for _, hid in train_human})
    rng = random.Random(SEED)
    judge = get_judge()
    with SessionLocal() as db:
        heads = {h.id: h for h in db.scalars(select(Headline).where(Headline.id.in_(head_ids))).all()}
        have = db.scalars(select(SyntheticFake).where(SyntheticFake.generator == generator,
                                                      SyntheticFake.headline_id.in_(head_ids))).all()
        got = Counter(f.edit_type for f in have)
        for kind, n in want.items():
            tries = 0
            while got[kind] < n and tries < 4:
                tries += 1
                need = n - got[kind]
                batch = [(i, heads[hid], kind) for i, hid in
                         enumerate(rng.sample(head_ids, min(len(head_ids), need + 2)))]
                for i, fake in _ask_control(provider, batch).items():
                    if got[kind] >= n or i >= len(batch):
                        continue
                    h = batch[i][1]
                    fake = " ".join(fake.split())
                    if not 1 <= word_diff(h.text, fake).num_changes <= config.MAX_WORD_CHANGES:
                        continue
                    ruling = judge_twice(judge, h.text, h.snippet, fake)
                    if not ruling.valid or ruling.vague:
                        continue
                    db.add(SyntheticFake(headline_id=h.id, text=fake, edit_type=kind,
                                         generator=generator,
                                         model=getattr(judge, "model", "") or ""))
                    got[kind] += 1
                db.commit()
            log(f"[control] {kind}: {got[kind]}/{n}")
        fakes = db.scalars(select(SyntheticFake).where(SyntheticFake.generator == generator,
                                                       SyntheticFake.headline_id.in_(head_ids))).all()
        out, used = [], Counter()
        for f in fakes:
            if used[f.edit_type] < want[f.edit_type]:
                used[f.edit_type] += 1
                out.append(Example(source_premise(db, heads[f.headline_id]), f.text, "refuted",
                                   f.edit_type, "synthetic"))
    return out


def pick_provider() -> str:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "claude"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    raise SystemExit("the synthetic control needs ANTHROPIC_API_KEY or OPENAI_API_KEY")


# --- external benchmark --------------------------------------------------------
VITAMINC_LABELS = {"SUPPORTS": "supported", "REFUTES": "refuted", "NOT ENOUGH INFO": "nei"}


def vitaminc(n: int, seed: int = SEED) -> list[Example]:
    """A seeded sample of the VitaminC test split (contrastive Wikipedia edits)."""
    from datasets import load_dataset

    ds = load_dataset("tals/vitaminc", split="test", streaming=True)
    rows = ds.shuffle(seed=seed, buffer_size=20_000).take(n)
    return [Example(r["evidence"], r["claim"], VITAMINC_LABELS[r["label"]], "", "vitaminc")
            for r in rows if r["label"] in VITAMINC_LABELS]
