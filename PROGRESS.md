# Sneak It Past — build progress

One section per phase of `prompt.md`. Each phase was run, tested and committed
before the next. The earlier TAPE game lives on the `main` / `full-game`
branches; parked live-forecasting work is on `live-forecast`.

| Phase | Status |
|---|---|
| 1. MVP: scrape, stub detector, editor + diff limit, judge, scoring, lives, logging, timer | ✅ |
| 2. Detector v0: LLM fakes, DistilBERT, live meter | ✅ (rule fakes until an API key is set) |
| 3. Addictive layer: multipliers, novelty, bounties, animations, near miss, share card | ✅ |
| 4. Patch days: retraining, versioning, "your exploit was patched" | ✅ |
| 5. Analytics dashboard | ✅ |
| 6. README: setup, architecture, schema, ethics | ✅ |

**State:** 42 backend tests passing, frontend typechecks clean, every phase played
through in Chrome. Live detector `v0` (held-out AUC 0.82, ~20 ms per meter call).

## Decisions where the spec was open

- **The detector reads headline + article snippet**, not the headline alone. A
  headline-only model can only learn the style of fakes; with the source it becomes
  claim verification, and patch days teach it things that generalise.
- **Bounties are the headlines the detector already suspects most** before any edit
  — the hardest place to hide a lie, which is why they pay 3× and get +5 s.
- **Near miss (40–50%) is a sneak**: it's under the 50% line, just barely.
- **Three invalid tries** end the round without losing a life, but reset the streak
  (otherwise skipping a hard headline would be free).
- **Judge unavailable** (network, rate limit, bad output) → the attempt isn't
  counted and the clock time is refunded.
- **Honest version comparison:** a fixed ~20% of exploits and of headlines are never
  trained on by any version; all versions are scored on them, with false alarms
  reported next to catches.
- **Mock-judged data** is tagged, excluded from patch days by default, and
  filterable on `/lab`.

## Phase notes

**1.** 118 real headlines captured from five RSS feeds as the offline seed
(explainer "Why/How…" headlines later filtered out: nothing checkable to twist).
Server-owned clock with judge pauses. Fixed in the browser pass: React dev mode
double-starting runs; the editor clipping three-line headlines on phones;
"Continue reading…" in Guardian snippets.

**2.** v0 first under-trained (4 epochs, loss barely moved, AUC 0.62); 10 epochs at
5e-5 gives AUC 0.82 on held-out headlines. The registry rechecks the live version
every 5 s so a patch day takes effect without restarting the API.

**3.** Novelty threshold 0.35 checked against hand-made pairs: same trick on a new
headline ~0.12, number-vs-number 0.34, different kinds of trick ~0.9. Sticky
meter + submit bar on phones so the keyboard can't hide them.

**4.** Patch day fine-tunes from the current version's weights on exploits, their
original headlines (the matched true set) and v0's data, then marks newly caught
exploits as patched and re-flags bounties. Dry-run verified on the live DB.

**5.** Palette = reference dark steps, validated on the real panel surface
(`#0b1020`), all-pairs pass. Every chart has a tooltip and a table view; legend
text in ink, never series colour.

## Prompt update: search-backed fact-checker (in progress → done below)

| Step | Status |
|---|---|
| Evidence corpus: article bodies → passages, BM25 retrieval, evidence / breaking-news modes | ✅ |
| Verifier v0 (DeBERTa-v3-base MNLI/FEVER/ANLI, off the shelf), SUPPORTED / REFUTED / NEI | ✅ |
| Outcomes from the verifier: snuck / partial / caught; evidence shown on reveal | ✅ |
| Judge v2: materiality, specificity, vagueness flags, 8 edit types, two runs must agree | ✅ |
| Scoring: materiality, sharp lie, too vague, partial; tags | ✅ |
| Human review: /admin queue, decisions log, counters, judge precision | ✅ |
| Evaluation: by-headline split, v0 / v1-synthetic / v1-human / v1-combined, VitaminC, bootstrap CIs | ✅ (pipeline verified on stand-in data; needs approved exploits for real results) |
| Patch day retrains the verifier (gated) | ✅ |
| Dashboard: failures by edit type, modes, model comparison, false positives, VitaminC, judge accuracy, progress | ✅ |
| README rewrite with project focus | ✅ |

**Findings on the way.** Off the shelf, with article bodies as evidence, v0 supported
35/40 true headlines (refuted none) and refuted 51/60 gpt-4.1 fakes — so wins in the
game are genuinely hard. Before the redesign, the old headline+snippet detector
couldn't learn LLM fakes at all (DistilBERT AUC ~0.55; it collapsed to "everything
false" and went live — the ship gate exists because of that). RSS snippets alone are
too thin: only 38% of LLM fakes even touch a word the snippet mentions, hence fetching
article bodies. BM25 on a small corpus needed an IDF-weighted relevance bar, or
generic shared words ("after", "death") pulled unrelated stories in as "evidence".

## After phase 6

- **OpenAI as an alternative provider** for the judge and v0's fakes (the team has
  OpenAI credit). Same prompt and schema as Claude (`judge/prompt.py`); `SIP_JUDGE=auto`
  prefers Anthropic, then OpenAI, then the mock. `python -m judge.check` verifies a
  key, lists usable models and judges two sample edits.

## Not done / needs a key or real players

- No LLM judge or LLM-written fakes have run against a live API (no key in this
  environment; unit tests stub the calls). Set a key in `.env`, run
  `python -m judge.check`, then `npm run fakes && npm run train-v0`, and play a round.
- No real patch day has shipped yet: it needs ≥ 5 judge-verified human exploits.
