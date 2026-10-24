# Project: "Sneak It Past" — a hackathon game that trains a misinformation detector

## Context
We're building this for an AI hackathon (judged partly on disinformation work and on "most fun"). The project must collect real data, analyze it, and train a model. Please read this whole spec, then propose a plan and file structure before writing code. Build in the phases listed at the bottom so we always have a working demo.

## The game in one sentence
Players get a TRUE news headline and edit up to 3 words to make it FALSE while keeping it sneaky enough that our AI misinformation detector still thinks it's true. Every trick that fools the detector becomes adversarial training data, and the detector periodically retrains ("patch days") so it gets harder over time.

## Core gameplay loop
1. Player is shown a real, true headline (plus a short snippet of the source article for context).
2. Player edits the headline in an inline editor. Max 3 word-level changes (substitutions, insertions, or deletions; compute with a word-level diff).
3. A live "suspicion meter" shows the detector's probability that the edited headline is false, updating as they type (debounce ~300ms).
4. Player hits Submit.
5. A judge model checks whether the edit actually makes the headline false relative to the original article, and that it's grammatical and plausible-sounding.
6. Outcome:
   - Judge says it's not false / nonsense → "Still true!" or "Nobody would believe that," no points, player can try again (max 3 attempts per headline).
   - Judge confirms false AND suspicion < 50% → SNUCK PAST. Award points, streak increases.
   - Judge confirms false AND suspicion >= 50% → CAUGHT. Lose a life, streak resets.
7. Run has 3 lives. Run ends when lives hit 0. Show a shareable result card.

## Scoring (make this feel juicy)
- Base points = round(1000 × (1 − suspicion))
- Word multiplier: 1 word changed = 3x, 2 words = 2x, 3 words = 1x
- Streak multiplier: 1 + 0.1 × current streak, capped at 2x
- Novelty bonus ("zero-day exploit"): embed the edit (original vs edited headline pair, and the changed words) with a sentence-transformer. If its minimum cosine distance to all previous successful exploits is above a threshold (make it configurable), award +50% and add the player's name to an "Exploit Board."
- Bounty headlines: some headlines are flagged as bounties (ones where the current detector is most overconfident). They're worth 3x and show a bounty badge.
- Animations: suspicion meter swings live, points count up, "SNUCK PAST" / "CAUGHT" stamps, near-miss message when suspicion lands between 40% and 50% ("so close!").

## The detector (must be fast)
- The live meter calls the detector on every debounced keystroke, so it must be a small fast model, NOT an LLM. Use a DistilBERT (or similar small) binary classifier that takes only the headline text and outputs P(false).
- Detector v0 baseline: train on (a) scraped true headlines labeled true, and (b) automatically generated false versions labeled false, created by asking an LLM to make small factual edits to true headlines. This gives us a baseline trained on LLM-made fakes.
- Patch days: a retraining script that takes all judge-verified successful player exploits (labeled false) plus a matched set of true headlines, and fine-tunes the next detector version (v1, v2, …). Keep every version so we can compare them.
- Track the detector version in every logged round.
- Players get a notification when one of their exploits gets "patched" (the new version catches it).

## The judge
- Uses the Anthropic API (model configurable via env var; default to a Claude Sonnet model). Called once per submission, not live.
- Input: original headline, article snippet, edited headline.
- Output strict JSON: { "is_false": bool, "is_plausible": bool, "is_grammatical": bool, "edit_type": string (e.g. "number change", "negation", "entity swap", "causal claim", "other"), "explanation": string }
- Validate the JSON and handle failures gracefully.
- Never put API keys in code; use environment variables and a .env.example.

## Data collection
- Scrape real true headlines plus short article snippets from news RSS feeds (make the feed list configurable). Store source URL and publish date. Deduplicate.
- Precompute bounty flags by running the current detector on the headline pool.
- Log EVERY attempt (not just successes) to the database:
  round_id, player_id (anonymous), timestamp, headline_id, original_headline, edited_headline, changed_words, num_words_changed, suspicion_score_final, suspicion_trace (the sequence of meter values while typing, with timestamps), judge_output (full JSON), outcome (snuck / caught / invalid), points, streak, lives_left, detector_version, novelty_distance, is_bounty, time_to_submit.
- The suspicion trace is important: it shows how players search for blind spots.

## Analytics dashboard (separate page for the demo)
- Detector accuracy on human exploits, by version (v0 → v1 → v2…). This is the headline chart for judges.
- v0 (trained on LLM-made fakes) vs later versions: show that human tricks find blind spots that LLM-generated training data misses.
- Breakdown of successful exploits by edit_type.
- Most common changed words in successful exploits.
- Exploit Board (top novel tricks).
- Totals: rounds played, exploits found, exploits patched.

## Ethics / handling (include in the README)
- All edited headlines are synthetic misinformation. Store them only in our database, clearly labeled synthetic. Never display player-made fakes outside the game without a "FAKE — made in Sneak It Past" label, and don't build any public feed of them.
- Show players a short notice that their edits are logged for research and model training.

## Tech stack (suggestions — push back if something simpler is better for a hackathon)
- Frontend: React (Vite or Next.js) + Tailwind. Mobile-friendly; most people will play on phones.
- Backend: Python FastAPI (serves the detector, calls the judge, handles scoring and logging).
- Database: SQLite for local dev, easy swap to Postgres/Supabase for deployment.
- ML: Hugging Face transformers for the detector, sentence-transformers for novelty embeddings.
- Training scripts should run on a free Colab GPU or a laptop CPU for small runs.

## Add: editing timer

Add a countdown timer to the editing phase of each headline to make rounds tense.

Rules:
- Each headline starts with a 20-second timer (make it configurable).
- The timer gets shorter as the player's streak grows: subtract 1 second per streak level, with a minimum of 10 seconds.
- Bounty headlines get +5 seconds since they're harder.
- All attempts on a headline (max 3) share the same clock. Pause the timer while the judge is evaluating a submission so API latency never costs the player time; resume it if the attempt was invalid.
- If the timer hits 0 before a successful submission, it counts as CAUGHT: lose a life and reset the streak.

Scoring:
- Add a time bonus multiplier: 1 + 0.5 × (seconds remaining / starting seconds). Fast sneaks can earn up to 1.5x.
- Apply it alongside the existing word, streak, novelty, and bounty multipliers.

Feel:
- Show the timer as a shrinking bar above the editor, not just a number.
- Last 5 seconds: the bar turns red, pulses, and the suspicion meter shakes slightly. Add an optional ticking sound (with a mute toggle).
- On a fast sneak (more than half the time left), show a "QUICK HANDS" bonus popup.
- On timeout, show a "TIME'S UP" stamp before moving on.

Logging (add to every attempt row):
- timer_start_seconds, time_remaining_at_submit, timed_out (bool).
- Keep the existing suspicion_trace timestamps so we can analyze how players search under pressure.

Analytics dashboard addition:
- Chart: success rate and average suspicion score vs. time remaining. This shows whether rushed tricks are sloppier or whether players find blind spots by instinct.

## Build phases (finish and test each before moving on)
1. MVP: scrape headlines, a stub detector (any quick baseline), the editor with word-diff limit, judge integration, basic scoring, lives, logging. Playable end to end.
2. Real detector v0: generate LLM-made fakes, train DistilBERT, wire up the live suspicion meter.
3. Addictive layer: streak/word/novelty multipliers, bounties, animations, near-miss messages, share card.
4. Patch days: retraining script, versioning, "your exploit was patched" notifications.
5. Analytics dashboard.
6. README with setup steps, architecture diagram, data schema, and the ethics section.

## Please
- Ask me any clarifying questions before starting.
- Keep the code simple and well-commented; teammates will be reading it.
- Write a seed script so the game works with a small sample of headlines even before scraping is set up.


# Update: Sneak It Past — project focus, detector redesign, anti-loophole scoring, and evaluation plan

This update REPLACES the earlier "detector" design and adds new judge rules, scoring, and a rigorous evaluation plan. Read it fully, tell me which existing code needs to change, then implement. The evaluation plan is as important as the game: we must be able to show judges a measurable, honest result.

## Project focus (put this at the top of the README)
We are NOT building a general "detect all misinformation" model. A text-only detector can't check facts, and subtle edits don't change a headline's style, so style alone isn't enough.

Our detector is a search-backed fact-checker. Search finds evidence, but fact-checking models often misread that evidence: numbers, swapped roles (who did what to whom), cause vs. correlation, time shifts, negation, and quantifiers. Players try to write false headlines that the fact-checker wrongly marks as SUPPORTED. Every win is a real fact-checker failure.

The game produces:
1. A dataset of human-found fact-checker failure modes
2. A verifier that improves on them through retraining
3. A controlled comparison showing whether human-found failures teach the model more than LLM-generated ones

## Two game modes
- Evidence mode (default): the retrieval index includes the source article. A player win means the verifier misread available evidence.
- Breaking news mode: the source article is excluded from retrieval, simulating a story with no coverage yet. Use this for bounty headlines. Track mode in every log row.

## Detector architecture (two parts)
1. Evidence verifier — decides the round:
   - Retrieval over our scraped article corpus (start with BM25; optionally hybrid with sentence-transformer embeddings). Return top-k passages (k configurable, default 3).
   - Verification with a small NLI / fact-verification model (e.g., a DeBERTa-v3 model fine-tuned on MNLI/FEVER-style data from Hugging Face) that takes (claim, evidence passages) and outputs probabilities for SUPPORTED / REFUTED / NOT ENOUGH INFO.
   - Runs on submit, not on every keystroke.
2. Style model — live meter only:
   - The existing fast small classifier keeps powering the live suspicion meter while typing, for game feel.
   - It does NOT decide outcomes. Label the meter in the UI as a "first glance" signal, and reveal the evidence verifier's verdict on submit.

## Outcomes (replace old snuck/caught logic)
After the judge validates the edit (see below):
- Verifier says SUPPORTED → SNUCK PAST (full points)
- Verifier says NOT ENOUGH INFO → PARTIAL (0.3x points, streak continues but doesn't grow)
- Verifier says REFUTED → CAUGHT (lose a life, reset streak)
On reveal, show the evidence passages the verifier used, so players learn why they were caught.

## Judge upgrades (anti-loophole)
Extend the judge's JSON output:
{
  "is_false": bool,
  "is_grammatical": bool,
  "is_plausible": bool,
  "materiality": 1-5,   // would a normal reader come away believing something false AND meaningful?
  "specificity": 1-5,   // is the edited claim as concrete and checkable as the original?
  "vagueness_flags": [string], // e.g. "added hedge: may", "number replaced with 'many'", "attributed to unnamed sources"
  "edit_type": one of ["number", "role swap", "causal", "temporal", "negation", "quantifier", "entity swap", "other"],
  "explanation": string
}
Rules:
- Write the judge prompt with an explicit rubric and examples of: pedantic edits (e.g. "the" → "a" with no real meaning change → materiality 1), material edits (e.g. "for" → "against" → materiality 5), vague edits (e.g. "52–48" → "narrowly", adding "may", "reportedly", "some say" → low specificity), and sharp edits (precise but wrong number or swapped name → high specificity).
- Run the judge twice (two different prompt phrasings). Both must agree that is_false is true. If they disagree, treat the edit as invalid.
- Materiality < 3 → invalid ("Too pedantic"), no points, no life lost.
- Specificity lower than the original by 2 or more, OR any vagueness flag → "Too vague": points × 0.5, or count it as CAUGHT if specificity ≤ 2.

## Scoring additions
Apply alongside the existing word, streak, time, novelty, and bounty multipliers:
- Materiality multiplier: 3 → 1x, 4 → 1.25x, 5 → 1.5x
- Specificity: kept equal to the original and specificity ≥ 4 → "Sharp lie" ×1.5
- Vagueness penalty as above
Show tags after each submit, e.g. "Sharp lie ×1.5", "Too vague −50%", "Too pedantic", "Misread evidence!" (on SNUCK PAST in evidence mode).

## Human review before retraining
- Add a simple admin review page listing successful exploits with original headline, edited headline, judge output, and evidence passages. Reviewers mark each approve / reject.
- Only approved exploits go into training or evaluation sets. Log reviewer decisions so we can measure judge accuracy.

## Data collection timeline (important — data volume is our biggest risk)
- As soon as the MVP is playable end to end, the team and friends start playing. Do not wait for polish.
- Target: at least 150 approved exploits before the first patch day.
- Run one patch day around the midpoint of the hackathon, then keep collecting so we can evaluate on fresh exploits.
- Add a simple counter on the admin page: attempts, judge-valid exploits, approved exploits, broken down by edit_type.

## Evaluation plan (build this as a script + dashboard section)

### Data splits
- Split approved exploits into train / test BY HEADLINE (no headline appears in both), ~70/30. Fix the random seed and save the split to disk so results are reproducible.
- Also hold out a set of TRUE headlines (unedited) with their evidence, never used in training, to measure false positives.
- Exploits collected after the patch day form an extra "fresh" test set.

### Models to compare (same base model, same training settings, same number of training examples)
1. v0: off-the-shelf verifier, no fine-tuning.
2. v1-synthetic (CONTROL): fine-tuned on LLM-generated tricky edits. Generate these with the Anthropic API by asking for minimal, material, specific false edits of the SAME training headlines, matched to the same edit_type distribution as the human exploits. Run them through the same judge filters. Use the same count as the human training set.
3. v1-human: fine-tuned on approved human exploits (labeled REFUTED) plus matched true headlines (labeled SUPPORTED) with their retrieved evidence.
4. (Optional) v1-combined: human + synthetic.

### Test sets
- Held-out human exploits (the main test)
- Held-out true headlines (false-positive check)
- Fresh post-patch exploits (if enough collected)
- External benchmark: a sample of VitaminC (a public fact-verification dataset built from minimal contrastive edits; load from Hugging Face). Use it to check that improvements generalize and the model doesn't get worse on standard data. Optionally also a FEVER sample.

### Metrics
- Refute recall on held-out exploits (how many lies are caught)
- False positive rate on true headlines (how many truths are wrongly refuted)
- Macro-F1 / accuracy on VitaminC
- All of the above broken down by edit_type
- Report every number with 95% bootstrap confidence intervals (1,000 resamples), since our sample sizes are small.

### The key claims to test
- Finding: which edit types the verifier misses most, even with evidence retrieved.
- Improvement: v1-human vs. v0.
- Main result: v1-human vs. v1-synthetic. Does human-found data teach something LLM-generated data doesn't?
- Sanity: no large jump in false positives, no drop on VitaminC.
Report honestly even if results are small or negative.

## Patch days (update)
- Retrain the EVIDENCE VERIFIER (not just the style model) as v1-human for the live game.
- Keep every model version and its eval results.
- Players get a "your exploit was patched" notification when the new version catches an exploit they found.

## Logging (add fields)
mode, retrieved_passage_ids, verifier_probs (supported/refuted/nei), verifier_verdict, judge_outputs (both runs), materiality, specificity, vagueness_flags, edit_type, review_status, reviewer_id, split (train/test/fresh), verifier_version.

## Dashboard (add charts)
- Verifier failure rate by edit_type (key finding)
- Evidence mode vs. breaking news mode win rates
- Model comparison table and bar chart: v0 vs. v1-synthetic vs. v1-human (vs. v1-combined) on each test set, with confidence intervals
- False-positive rate by version
- VitaminC score by version
- Judge accuracy vs. human review
- Data progress: approved exploits over time, by edit_type