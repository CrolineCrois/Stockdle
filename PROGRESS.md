# TAPE: Draw It — build progress

Running log, one section per phase. All ten phases are done; each was run and
verified before moving on.

| Phase | Status |
|---|---|
| 1. Scaffold, seed data, round builder | ✅ |
| 2. Scoring + tests | ✅ |
| 3. Base forecaster + training | ✅ |
| 4. FastAPI backend | ✅ |
| 5. Canvas + round loop | ✅ |
| 6. Daily 5, Endless, streaks, share, leaderboard | ✅ |
| 7. Crowd + blend + retraining + versions | ✅ |
| 8. Dashboard | ✅ |
| 9. Live scrapers | ✅ |
| 10. Demo seed, polish, README | ✅ |

**Current state:** 195 rounds live (Google Trends real, the rest seed), 63 tests
passing, model skill +61% / +44% / +19% / +19% vs persistence by round type,
demo cohort of 40 players × 600 drawings across 24 AI versions.

---

## Phase 1 — scaffold, seed data, round builder ✅

`pipeline/seed_gen.py` writes `data/seed/{electricity,stock,trends}.json`: 3
balancing authorities × 150 days hourly with a diurnal load shape and aligned
temperatures; 12 tickers × 24 sessions × 390 one-minute bars as jump diffusion
with headline-reactive drift; 14 search terms × 14 years weekly with a
wrapped-Gaussian season.

`pipeline/build_rounds.py` cuts rounds and a disjoint training set, asserting at
build time that no training window shares a source index with a game round.
`pipeline/plot_rounds.py` renders `data/rounds/round_preview.png` — the twelve
sampled rounds read as real load curves, price tapes and search seasons.

**Changed from the spec**

- Python 3.13.1 rather than 3.11 (what is installed; nothing needed 3.11).
- No `make` on this machine, so the single entry point is `npm run dev`, which
  the spec allows. A `Makefile` wrapping the npm scripts is there anyway.
- Fake rounds are cut from *quiet* windows (≥180 bars from any real headline) so
  the hidden half is genuinely a non-reaction.
- Round counts are allocated from measured source capacity against a target mix
  rather than a fixed per-type quota — see phase 9 for why.

## Phase 2 — scoring ✅

`scoring.py` implements the spec formula with the constants tuned as invited:
`SIGMA_MULT` 5 → 9 and `SIGMA_FLOOR` 0.05 → 0.09. At the spec's defaults a
simulated "decent" player scored ~55 and a "great" one ~83, below the 60–85 /
90+ targets. Retuned, `python -m scoring --calibrate` reports decent 70–75 and
great 89–92 across all four round types. `K` stayed at 1.2.

Turning-point detection measures prominence against the *higher* of the two
endpoints, so a monotone ramp — whose max is its last point — never counts as a
turning point. 35 unit tests.

## Phase 3 — base forecaster ✅

Per-type multi-output Ridge over 30 anchored lags + 9 shape stats + type
context, alpha by grid search. Features and targets are deltas from the last
visible point, so predictions are level-invariant and start where the visible
line stopped.

Held-out error on game rounds the model has never seen:

| Type | Model | Persistence | Skill |
|---|---|---|---|
| electricity | 0.124 | 0.319 | +61% |
| stock | 0.174 | 0.308 | +44% |
| trends | 0.188 | 0.233 | +19% |
| fake_stock | 0.169 | 0.208 | +19% |

`is_fake` is deliberately **not** a feature — see the README's responsible-design
section.

## Phase 4 — backend ✅

All specified endpoints, SQLite via SQLAlchemy 2.0. `public_round()` is the
single choke point for round serialisation; a test walks every pre-submit
payload recursively for the truth curve. One scored drawing per player per round
(unique constraint) plus a sliding-window rate limit.

Verified with pytest and curl against a running server.

## Phase 5 — canvas and round loop ✅

One canvas draws the chart and takes the input, in a single rAF loop that never
re-renders React during a stroke. 50 slots, one y per x, later strokes overwrite,
gaps bridged by interpolation during the stroke and on commit. Pointer events
with `touch-action: none`, DPR-aware, `ResizeObserver` for responsiveness.

Reveal: truth traces left-to-right over 1.2s with the gap to the player's line
shaded, then crowd (dashed) and AI (dotted) ghosts fade in, then the score
counts up with bonus chips landing one at a time.

**Changed from the spec:** the 10-second clock starts on the player's **first
stroke**, not when the round renders. Reading the context card is part of the
puzzle and shouldn't cost clock; everyone still gets exactly ten seconds to
draw. A separate 30s idle timeout skips a round nobody touches.

## Phase 6 — modes, streaks, share, leaderboard ✅

Daily 5 is derived from the date alone (`app/daily.py`) — no stored schedule, so
any server reproduces it. The mix is one round of each type plus a wildcard.
Share string: `TAPE #14 🎯 87 · 92 · 41 · 78 · 99 | beat AI 4/5`, scores only,
with a copy button. Endless tracks a streak flame and multiplier badge.

## Phase 7 — crowd, blend, retraining ✅

Crowd curve is a running pointwise mean, used once a round has 3 drawings. The
blend weight `w` per type is grid-searched over [0, 1] against real outcomes
every 25 drawings, in a FastAPI background task, writing an `ai_versions` row
with model-only / crowd-only / blend RMSE on a stable held-out split.

Submitting computes the AI and crowd curves *before* folding the new drawing in,
so nobody is scored against a crowd mean containing their own line.

From the demo cohort: blend 0.146 vs model-only 0.172 vs crowd-only 0.242 — the
blend beats both inputs, which is the dashboard's headline. The learned weights
are themselves the interesting result: `electricity w=0.85` (trust the model —
people cannot read load curves), `trends w≈0.4` (trust the crowd — people are
good at seasons).

## Phase 8 — dashboard ✅

Four questions, four forms: 3-series line over AI versions, single-series bar
for player improvement, diverging bar around zero for signed bias, grouped bar
for fake-vs-real headline reaction. Plus hero stat tiles and the current blend
weights. Polls every 12s so it stays live during a pitch.

Chart colours were validated with the data-viz palette validator against the
app's own chart surface. The first attempt (`#38bdf8` / `#a78bfa` / `#ffd24a`)
**failed** — blue and violet sit at CVD ΔE 5.2 under deuteranopia. The shipped
palette passes all checks for the 3-series dashboard (worst ΔE 13.2) and
all-pairs for the 4-series canvas (worst ΔE 6.9, inside the floor band that
requires secondary encoding — supplied by distinct line styles, an always-present
legend, and direct labels). Documented in `frontend/lib/palette.ts`.

**Fixed:** `(player_round_index - 1) / 5` rendered as float division in SQL, so
every round number became its own "bucket" (0.0, 0.2, 0.4 …) and the chart had
one bar per round instead of per five. Now floor division, with a regression
test.

## Phase 9 — live scrapers ✅

All four sources implemented with the live → cache → seed ladder. Verified by
running each against the real network:

- **Open-Meteo**: live, no key. Fetched 144 real hourly temperatures for Dallas.
- **EIA**: needs a free `EIA_API_KEY`, absent here, so electricity falls back to
  seed as designed.
- **yfinance**: Yahoo rate-limited us (`YFRateLimitError`), so stocks fall back
  to seed. Handled, not fixable from our side.
- **pytrends**: **now live, all 14 terms, 260 weeks each.** Two real bugs found
  and fixed:
  1. Passing `retries=`/`backoff_factor=` to `TrendReq` makes it build a urllib3
     `Retry` with `method_whitelist`, removed in urllib3 2.x — every request
     raised `TypeError`. The constructor is now bare and backoff lives in our
     own retry loop.
  2. Google Trends normalises interest *within a request*. Batching three terms
     scaled them all against the biggest, flattening "tax extension",
     "air fryer recipes" and "new year resolutions" to a dead 0–1 line. Terms
     are now fetched one at a time, and every term spans a full 0–100.

Three further changes came out of running live:

- **Per-type window geometry.** Live Trends serves 5 years weekly (260 points);
  a 125-step window fits twice, leaving nothing to train on. Trends rounds now
  span 60 real weeks visible → 26 hidden, resampled onto the canvas' 75/50.
  Better puzzle too: half a year ahead, not two and a half.
- **Capacity-based quota allocation.** Rather than a fixed 50-per-type split,
  the builder measures how many non-overlapping windows each source can supply
  and allocates a ~200-round catalogue against a target mix with per-type
  ceilings. Without the ceilings, fake rounds (effectively unlimited capacity)
  took 144 of 202 slots.
- **Action-aware trends selection.** Block-aligned cutting put the seasonal
  spike for narrow terms in the *visible* half, leaving a flat hidden half with
  nothing to predict. Candidate cuts are now scored by how much of the window's
  range falls in the hidden half, and only the best non-overlapping ones ship.

Live build: 195 rounds (electricity 63, stock 70, fake 48, trends 14) + 3,649
training windows. Offline/seed build: 186 rounds + 5,579 windows.

## Phase 10 — demo, polish, README ✅

`scripts/seed_demo.py` creates 40 simulated players with distinct personalities
(skill tiers, headline gain, hand smoothness, herding) and ~600 drawings,
retraining every 25. Resettable with `npm run reset-demo`. Simulated players are
flagged `is_bot` and labelled `sim` on the leaderboard.

**Changed from the spec:** the first version modelled each player as
truth-plus-independent-noise, which made the crowd mean converge on the truth
and "the crowd beats the model" an artifact of the simulator. Players now share
a round-specific **crowd misread** — everyone is pulled part-way from the truth
toward the naive drift line, because real forecasters over-extrapolate recent
slope. The crowd is now worse than the model on average and the blend genuinely
beats both, which is the honest version of the result.

Shift+R on `/play` forces a retrain live (guarded by `TAPE_ADMIN_TOKEN`).

**Fixed:** a pipeline rebuild changes round ids (they hash the cut position), and
the superseded rows stayed in the database and kept being dealt — serving stale
context text and geometry. The catalogue sync now **retires** absent rounds
rather than deleting them, so drawings and leaderboard scores that reference them
stay intact, and every dealing query filters on `active`. Includes an additive
SQLite migration so an existing demo database is not lost, and two regression
tests.

---

## Verified

- `npm test` → 63 passing (35 scoring, 28 API/integration).
- `npm run dev` starts both servers; all four pages return 200.
- `npx tsc --noEmit` clean; `next build` clean, 5 routes prerendered.
- Full Daily-5 play-through over HTTP: rounds served without `hidden`, scoring
  with bonuses, crowd and AI curves, fake reveal, share string carrying no
  headline text, leaderboard and AI version endpoints.

## Not verified

- **No browser was driven.** The pages render and typecheck, the canvas logic is
  unit-reasoned, but the drawing feel, the reveal animation timing, touch input
  and the mobile layout have not been looked at by a human or a screenshot. That
  is the first thing to check.

---

## Post-build: browser pass (2026-10-24)

First time the app was driven in a real browser. Changes that came out of it:

- **Fake-headline rounds removed.** With a warning label shown before drawing,
  players had no way to *detect* a fake — the round only tested whether they
  ignored a labelled rumour. Cut from the pipeline, game, dashboard and README;
  the `is_fake` DB columns stay so older databases still load. Catalogue is now
  179 rounds (grid 63, stock 80, trends 36).
- **Local-time x-axis.** Timestamps were UTC end to end, so the grid card's
  "cut at 21:00" in Los Angeles was really 2pm. Rounds now carry an `x_axis`
  block (clock / day / month ticks, night bands on grid rounds, the time at the
  cut) and the canvas draws it.
- **Seed grid data fixed.** The load shape keyed off the UTC hour (LA peaked at
  11am) and the weather was an unbounded random walk (123°F in LA). Now local
  hour and a mean-reverting AR(1) anomaly; highs land 71–113°F.
- **Fixed:** "Keep playing (Endless)" after a Daily stayed stuck on the summary
  (same-route navigation never reloaded); `reset-demo` stranded every browser
  that had played before on "Unknown player" (the client now re-registers).
- **Demo seed** spreads its crowd-heavy rounds evenly across types, so every
  type gets a blend weight.
