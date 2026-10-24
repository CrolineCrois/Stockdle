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
