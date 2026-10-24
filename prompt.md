I'm building a hackathon demo called **TAPE: Draw It**: an addictive web game where players predict the future of real-world charts by drawing a line, and their drawings help train an AI. Please build it end to end following this spec. Work in the phases below, run and verify each phase before moving on, and keep a short PROGRESS.md updated. Prioritize a working, polished demo over completeness: if something is hard (an API is down, a library breaks), use the fallback described and keep going.

---

## 1. Game concept

Each round:
1. A chart appears with the first ~60% of the line visible, plus a context card (e.g. a news headline, a temperature forecast, or a search term).
2. The remaining area is blank. The player has 10 seconds to draw their prediction of how the line continues (mouse or touch).
3. On submit, the real line animates in over the player's line (~1.2s), and the area between them is shaded.
4. Then two "ghost" lines fade in: the crowd's average drawing for this round and the AI's prediction.
5. Score pops up with bonuses, streak updates, and a "Next" button (Enter/Space also advances).

Modes:
- **Daily 5:** the same 5 rounds for everyone today (deterministic by date). At the end, show a shareable emoji result like:
  `TAPE #14 🎯 87 · 92 · 41 · 78 · 99 | beat AI 4/5`, with a copy-to-clipboard button.
- **Endless:** random rounds and a streak counter until you choose to stop.

Players enter a display name only (no auth), stored in localStorage plus a players table.

---

## 2. Tech stack and repo layout

- `backend/`: Python 3.11, FastAPI, SQLite (via SQLAlchemy or sqlite3), pandas, numpy, scikit-learn. Optional: sentence-transformers (`all-MiniLM-L6-v2`) for headline embeddings, with a fallback to VADER sentiment plus simple keyword features if it fails to install or load.
- `frontend/`: Next.js (App Router, TypeScript), Tailwind, HTML canvas for drawing and charts (no heavy chart library needed; draw it ourselves so the animation is smooth). Framer Motion for UI animation is fine.
- `data/`: `raw/` (cached scrape output), `seed/` (bundled fallback data checked into the repo), `rounds/` (processed rounds).
- Root `README.md` with setup steps and a single `make dev` (or npm script) that starts both servers.
- Config via `.env` (e.g. `EIA_API_KEY`, optional `ANTHROPIC_API_KEY`). Everything must still run with no keys, using the seed data.

---

## 3. Data pipeline (`backend/pipeline/`)

Write one scraper module per source. Each must: (a) try the live source, (b) cache results to `data/raw/`, (c) on any failure, fall back to `data/seed/`. Generate realistic seed data for every source now so the app always works offline. Use real-looking structure (e.g. daily load curves with temperature-driven peaks), clearly marked as seed.

Sources:
1. **Electricity demand:** hourly demand from the EIA Open Data API v2 (EIA-930 balancing authority data, e.g. ERCOT, PJM, CAISO) plus hourly temperature for a representative city per region from the Open-Meteo historical API (free, no key). Context card: "Region: ERCOT · Forecast high 104°F · Tuesday".
2. **Stocks plus headlines:** intraday prices from `yfinance` and recent headlines via `yfinance` Ticker news (title plus publish time). Align each headline to the price series at its publish timestamp: the visible part ends at the headline time, the hidden part is what happened after. Context card: the headline plus the ticker hidden until reveal (show "Mystery stock" before, ticker and date after).
3. **Google Trends:** weekly interest over time via `pytrends` for a curated list of fun, seasonal terms (e.g. "pumpkin spice", "flu symptoms", "sunscreen", "world cup", "tax extension"). pytrends is often rate-limited, so cache aggressively and rely on seed data if needed. Context card: the search term.
4. **Fake-headline rounds (disinformation angle):** take real stock charts and pair them with a fabricated headline (e.g. fake CEO resignation, fake regulatory ban). Generate the fakes with the Anthropic API if `ANTHROPIC_API_KEY` is set, otherwise use a template list of ~20. The hidden part is the real price path, which did NOT react to the fake news. After the reveal, show a clear banner: "This headline was FAKE. Here's what really happened." Store `is_fake = true`. Fake headlines must never appear outside a round with that label, and the share text must never include headline text.

**Round builder** (`build_rounds.py`): cut series into rounds with:
- `id`, `type` (`electricity` | `stock` | `trends` | `fake_stock`), `visible` (array of y-values), `hidden` (array of exactly 50 y-values), `context` (JSON for the card), `reveal_info` (JSON shown after, e.g. ticker/date/region), `is_fake`.
- Normalize y-values per round to a 0–1 range based on the full (visible+hidden) min/max with 10% padding, so drawings are on a common scale. Store the scale so axis labels show real units.
- Build ~200 game rounds and a separate, larger set of historical training windows for the model (no overlap with game rounds).

---

## 4. Scoring (`backend/scoring.py`)

Inputs: player curve (50 points, normalized), true hidden curve (50 points), visible curve.
- `sigma` = standard deviation of the true hidden curve's first differences, floored at a small epsilon, to normalize for volatility.
- `err` = RMSE(player, truth) / max(sigma × 5, 0.05) (tune constants so a decent guess scores 60–85 and a great one 90+).
- Base score = round(100 × exp(−1.2 × err)), clamped 0–100.
- Bonuses:
  - **Turning point (+25):** if the true curve's global max or min in the hidden region is a clear extremum, award the bonus when the player's corresponding extremum is within 3 x-steps.
  - **Direction (+10):** sign of (end − start) matches the truth.
  - **Beat the AI (+20)** and **beat the crowd (+20)**, based on raw RMSE comparisons (crowd only counts once the round has at least 3 prior drawings).
- **Bullseye:** base score ≥ 95 triggers a special animation.
- **Streak:** consecutive rounds with base ≥ 75 add a multiplier of 1 + 0.1 × streak (cap 2×).
Write unit tests for scoring.

---

## 5. The AI (`backend/model/`)

Be honest in naming: the AI is a forecasting model, and players improve it through a crowd-blend layer.

1. **Base forecaster (per round type):** multi-output Ridge regression (or a small GradientBoosting per output, if fast enough) mapping features to the 50 hidden points. Features: the last ~30 visible points (resampled), simple stats (slope, volatility, last value), plus type-specific context (temperature, hour/day for electricity; headline embedding or sentiment for stocks; month/seasonality for trends). Train on the historical windows, not the game rounds.
2. **Crowd forecast:** per round, the pointwise mean of all player drawings (store a running mean).
3. **Blend model:** prediction = w × model + (1 − w) × crowd, with w learned per round type by minimizing error over rounds where both exist (a simple grid search over w in [0, 1] is fine). Fall back to model only when a round has fewer than 3 drawings.
4. **Retraining and versions:** every 25 new drawings (configurable), re-fit the blend weights, and re-fit the base model if new data is available. Each retrain creates an `ai_versions` row with a version number, timestamp, and error metrics (model-only, crowd-only, and blend RMSE on a held-out set of completed rounds). The frontend shows a toast: "⚡ TAPE AI v7 deployed — learned from 25 new drawings."
5. Run retraining in a FastAPI background task so it never blocks gameplay.

---

## 6. Backend API (FastAPI)

- `GET /api/round/next?mode=daily|endless&player_id=` → round **without** the `hidden` field (never leak the answer before submit).
- `GET /api/daily` → today's 5 round ids (deterministic seed from date).
- `POST /api/round/{id}/submit` with `{player_id, curve: number[50], time_ms}` → validates the curve, stores the drawing, returns `{truth, ai_curve, crowd_curve, score_breakdown, reveal_info, is_fake, streak}`.
- `GET /api/leaderboard?period=today|all`
- `GET /api/dashboard` → stats for the dashboard page (below).
- `GET /api/ai/version` → current version, for the toast.
SQLite tables: `players`, `rounds`, `drawings`, `ai_versions`. Add simple input validation and rate limiting (e.g. max 1 submit per round per player).

---

## 7. Frontend

Pages:
- `/`: landing with the game name, a one-line pitch ("Draw the future. Beat the AI. Teach it something."), name input, and buttons for Daily 5 and Endless.
- `/play`: the main game.
- `/leaderboard`
- `/dashboard`: the "science" page for judges.

**Drawing canvas (most important component):**
- Chart on a canvas: visible line drawn solid, a vertical dashed "now" line at the cut point, blank prediction region to its right, light gridlines, and real-unit axis labels.
- The player draws only in the prediction region. Map pointer x to one of 50 slots; keep **one y per x** (a new stroke overwrites earlier values in the slots it covers); linearly interpolate gaps; snap the start of the drawing to the last visible point visually.
- Submit is enabled once ≥ 90% of the slots are covered. The 10-second timer auto-submits if coverage is enough; otherwise the round is skipped with score 0.
- Works on touch (pointer events, `touch-action: none`), and is responsive on phone and laptop.
- Reveal sequence: the truth line traces left-to-right (~1.2s), the gap between player and truth is shaded, then the crowd (dashed) and AI (dotted) ghost lines fade in with a legend, then the score counter animates up with bonus chips appearing one by one. Bullseye: screen shake plus confetti.
- Fake rounds: after the reveal, show a prominent banner explaining that the headline was fake and what the stock really did.

**Game feel:**
- Snappy transitions, preloading the next round during the reveal.
- A streak flame indicator; a score multiplier badge.
- AI version toast when a new version deploys.
- Simple sound effects (draw, reveal, bullseye) using small generated tones via the Web Audio API, with a mute toggle.
- Dark, high-contrast visual style that looks good on a projector. Clean, modern, not generic.

**Dashboard (`/dashboard`):**
1. AI version history: line chart of model-only vs crowd-only vs blend error across versions (the headline graph: "humans + AI beat either alone").
2. Player improvement: average score by round number (rounds 1–5, 6–10, …) across all players.
3. Human bias findings: average signed error by round type (do players overreact or underreact?), and for stock rounds, the average predicted move for fake vs real headlines.
4. Totals: drawings collected, players, current AI version.
Use a lightweight chart library (Recharts is fine) for the dashboard only.

---

## 8. Demo-readiness

- A seed script that simulates ~40 players making ~600 drawings with realistic noise (some players good, some biased toward overreacting to headlines) and runs several retrains, so the dashboard and ghost lines look alive at demo time. Make it resettable (`make reset-demo`).
- An admin keyboard shortcut or env flag to force a retrain live during the pitch.
- README sections: setup, running, data sources, how the AI learns, responsible design (fake headlines are labeled, never exported as text, and exist to teach detection), and known limitations.

---

## Phases (verify each before moving on)

1. Repo scaffold, seed data for all sources, round builder → confirm rounds are generated and look sensible (write a quick script that plots a few to PNG).
2. Scoring module with tests.
3. Base forecaster and training script → report baseline error per round type.
4. FastAPI backend with all endpoints → test with curl/pytest; confirm `hidden` never leaks.
5. Frontend drawing canvas and the full round loop (draw → submit → reveal → score → next).
6. Daily 5, Endless, streaks, share grid, leaderboard.
7. Crowd forecast, blend model, retraining, versions, toast.
8. Dashboard.
9. Live scrapers (EIA, Open-Meteo, yfinance, pytrends, fake headlines) with fallbacks.
10. Demo seed script, polish pass on animations and mobile, README.

When you finish each phase, summarize what works and anything you had to change from this spec.