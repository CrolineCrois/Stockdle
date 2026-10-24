# TAPE: Draw It

**Draw the future. Beat the AI. Teach it something.**

A chart appears with its last stretch cut off. You get ten seconds to draw what
happened next. Then the truth traces in over your line, two ghost lines fade up
— what the crowd drew, and what the AI predicted — and you find out whether you
beat either of them. Your drawing then becomes part of what the AI learns from.

Three kinds of round, all from real-world series:

| Round | What you are predicting | Your clue |
|---|---|---|
| **Grid demand** | The next 50 hours of electricity load for a US balancing authority | Region and the temperature forecast |
| **Mystery stock** | The next 50 bars after a real headline dropped | The headline. Ticker and date stay hidden until the reveal |
| **Search trends** | The next 26 weeks of Google search interest | The search term |

---

## Quick start

```bash
npm run setup     # venv, dependencies, seed data, rounds, trained model
npm run dev       # API on :8000, web app on :3000
```

Then open **http://localhost:3000**.

`make setup` / `make dev` work too, if you have make; they just call the npm
scripts, which handle the Windows/POSIX virtualenv path difference.

Everything runs with **no API keys and no network**. The repo ships
`data/seed/`, a bundled fallback for every source, so a cold clone is playable.

For a demo that already looks alive — populated leaderboard, crowd ghost lines,
a real AI version history on the dashboard:

```bash
npm run seed-demo    # ~40 simulated players, ~600 drawings, ~24 AI versions
```

### Requirements

Node 18+ and Python 3.11+ (developed on 3.13). Nothing else.

---

## What the commands do

| Command | What it does |
|---|---|
| `npm run setup` | Creates `backend/.venv`, installs, generates seed data, builds rounds, trains the model, installs frontend packages |
| `npm run dev` | Runs the FastAPI backend and the Next.js app together |
| `npm run pipeline` | Rebuilds rounds, trying the **live** sources first |
| `npm run pipeline:offline` | Rebuilds rounds from cache/seed only, no network |
| `npm run train` | Refits the base forecasters and prints held-out error per round type |
| `npm run plot` | Renders `data/rounds/round_preview.png` to eyeball the rounds |
| `npm run seed-demo` | Adds the simulated demo cohort |
| `npm run reset-demo` | Wipes all play data, then re-seeds it |
| `npm test` | Backend test suite (63 tests) |

---

## Data sources

Every scraper follows the same ladder: **try live → cache to `data/raw/` → fall
back to `data/seed/`**. A source being down, rate-limited or keyless never
breaks the game; it just means those rounds come from the seed archive, and the
UI marks them with a `seed data` chip.

| Source | Live via | Key | Notes |
|---|---|---|---|
| Electricity demand | [EIA Open Data v2](https://www.eia.gov/opendata/) (EIA-930 hourly demand) | `EIA_API_KEY` (free) | ERCOT, PJM, CAISO |
| Temperature | [Open-Meteo archive](https://open-meteo.com/) | none | Hourly, joined to the demand series |
| Stock prices + headlines | `yfinance` | none | 5-minute bars; each headline aligned to the bar at its publish time |
| Search interest | `pytrends` | none | Weekly, 5 years, **one term per request** (see below) |

Two things worth knowing if you re-run the pipeline:

- **Google Trends normalises within a request.** Asking for three terms at once
  scales them all against whichever is biggest, which flattened low-volume terms
  like "tax extension" to a dead 0–1 line. Terms are fetched one at a time so
  each is scaled to its own peak.
- **Live Trends only serves 5 years at weekly resolution.** That is why trends
  rounds use a different window (60 weeks visible → 26 weeks hidden, resampled
  onto the canvas' 75/50 points) while hourly and minute sources use 75 → 50
  directly. A 125-week window fits into 260 weeks barely twice, leaving nothing
  to train on.

All source timestamps are stored in UTC, but everything a player reads is on
the local clock: grid rounds use the balancing authority's time zone (ERCOT
Central, PJM Eastern, CAISO Pacific) and stock rounds use Eastern market time.
Each round carries an `x_axis` block (tick labels, night bands for grid rounds,
the time at the cut) so the canvas can label the time axis — demand depends
heavily on time of day, and a minute index alone is hard to reason about.

Round counts adapt to whatever the sources served: the builder measures how many
non-overlapping windows each source can supply and allocates a ~200-round
catalogue against a target mix, so a thin source shrinks its own slice rather
than the whole game.

---

## How the AI learns

The naming here is deliberate — "the AI" is a forecasting model, and players
improve it through a crowd-blend layer. Three separable pieces:

**1. Base forecaster** (`backend/model/`) — one multi-output Ridge regression per
round type, mapping 30 anchored lags + 9 shape statistics + type-specific context
(temperature and hour/day for grid; headline sentiment for stocks; week and month
harmonics for trends) to the 50 hidden points. It is fit on *historical windows*
and never sees a game round: the builder asserts at build time that no training
window shares a single source index with any playable round.

Held-out error on the 179 game rounds it has never seen (offline build),
against a persistence baseline (a flat line):

| Round type | Model RMSE | Persistence | Skill |
|---|---|---|---|
| Grid demand | 0.099 | 0.316 | **+69%** |
| Stock headline | 0.174 | 0.307 | **+43%** |
| Search trends | 0.147 | 0.301 | **+51%** |

**2. Crowd forecast** — a running pointwise mean of every drawing submitted on a
round. A round needs 3 drawings before its crowd line is used at all.

**3. Blend** — `prediction = w × model + (1 − w) × crowd`, with `w` fit per round
type by grid search over [0, 1] against real outcomes. **This is the part human
play actually moves.** Every 25 drawings (configurable) a FastAPI background task
re-fits the weights, re-fits the base model if the pipeline produced new data,
and writes an `ai_versions` row with model-only, crowd-only and blend error on a
held-out split of rounds. The client picks that up and toasts
*"⚡ TAPE AI v7 deployed — learned from 25 new drawings."*

The weights it learns are themselves the interesting result. From the demo
cohort: `electricity w=0.90` (people cannot read load curves — trust the model),
`stock w=0.45` and `trends w=0.60` (the crowd earns a real share). And the blend
beats both of its inputs, which is the dashboard's headline chart.

### Scoring

```
sigma = std(diff(truth))                       # the round's own volatility
err   = RMSE(you, truth) / max(sigma × 9, 0.09)
base  = round(100 × exp(−1.2 × err))           # clamped 0–100
total = (base + bonuses) × streak multiplier
```

Dividing by the round's volatility is what makes a score mean the same thing on
a jagged load curve and a quiet stock tape. Constants are tuned so a decent
drawing lands 70–75 and a great one 90+ (`python -m scoring --calibrate` prints
the table). Bonuses: turning point +25 (your extremum within 3 steps of the
truth's, when the truth has a clear one), direction +10, beat the AI +20, beat
the crowd +20. Base ≥ 95 is a bullseye; base ≥ 75 extends a streak, worth
+0.1× per round up to 2×.

---

## Responsible design

- **Simulated demo players are labelled `sim`** on the leaderboard. Seeded play
  should not be mistaken for a real crowd.
- **Share strings carry scores only** — no headline, ticker or round id — so a
  result can be posted without spoiling or quoting anything.

Identity is a display name in `localStorage` plus a row in `players`. No email,
no password, no tracking.

---

## Architecture

```
backend/
  pipeline/        one module per source + the round builder
    seed_gen.py      bundled fallback data for every source
    electricity.py   EIA v2 + Open-Meteo
    stocks.py        yfinance prices and headlines
    trends.py        pytrends search interest
    build_rounds.py  cuts series into rounds + disjoint training windows
    plot_rounds.py   PNG sanity check
  model/
    features.py      round -> feature vector (anchored, level-invariant)
    forecaster.py    per-type multi-output Ridge, alpha by grid search
    blend.py         fits w for model/crowd blending
    text.py          headline features (VADER + lexicon; MiniLM if enabled)
    train.py         fits everything, reports held-out error
  app/
    main.py          FastAPI routes
    ai.py            forecaster + crowd + blend + versioning
    daily.py         deterministic Daily 5 and the share string
    schemas.py       request/response models and `public_round`
    models.py        players, rounds, drawings, ai_versions
  scoring.py         scoring, bonuses, streaks
  scripts/seed_demo.py  the simulated demo cohort
frontend/
  app/             landing, /play, /leaderboard, /dashboard
  components/      DrawCanvas, ContextCard, ScorePanel, charts, Confetti, Toast
  lib/             api client, validated chart palette, Web Audio kit
data/
  seed/            committed fallback data
  raw/             scraper cache (gitignored)
  rounds/          built rounds + training windows (gitignored)
```

### API

| Endpoint | Purpose |
|---|---|
| `POST /api/player` | Create or rename a player |
| `GET /api/round/next?mode=daily\|endless&player_id=` | Next round, **without** `hidden` |
| `GET /api/daily` | Today's five round ids |
| `POST /api/round/{id}/submit` | Score a drawing; returns truth, AI, crowd, breakdown |
| `GET /api/player/{id}/daily` | Daily 5 result and share string |
| `GET /api/leaderboard?period=today\|all` | Standings |
| `GET /api/ai/version` | Current AI version, for the toast |
| `GET /api/dashboard` | Everything on `/dashboard` |
| `POST /api/admin/retrain` | Force a retrain (needs `x-admin-token`) |

`public_round()` in `app/schemas.py` is the single choke point for serialising a
round, and strips `hidden`, `feat` and `span`. A test walks every pre-submit
payload recursively looking for the truth curve.

Input validation: curves must be exactly 50 finite numbers (values are clamped
to 0–1 rather than rejected), one scored drawing per player per round enforced by
a unique constraint, and a sliding-window rate limit per player.

---

## Demo notes

- **Shift+R** on `/play` forces an AI retrain live (guarded by
  `TAPE_ADMIN_TOKEN`). Good for showing the version toast on stage.
- `/dashboard` polls every 12 seconds, so it updates while people play.
- `npm run reset-demo` puts the demo back to a known state between runs.
- The dark, high-contrast palette is built for a projector. Chart colours were
  validated for colour-vision deficiency against the app's own surface; the four
  canvas lines also differ in stroke style and carry a legend, so identity is
  never on hue alone.

---

## Known limitations

- **Seed data is synthetic.** It is shaped to match each source (diurnal load
  curves with a temperature-driven evening peak, jump-diffusion prices,
  wrapped-Gaussian search seasons) but it is not history. Rounds built from it
  are chipped `seed data`. Run `npm run pipeline` with a network and an
  `EIA_API_KEY` for the real thing. In particular, **seed headlines are
  invented templates attached to real tickers** — "Microsoft announces $10B
  buyback expansion" over a synthetic price path did not happen. Live stock
  rounds use real yfinance headlines.
- **yfinance is frequently rate-limited** by Yahoo. When it is, stock rounds come
  from the seed archive. There is no fix for this on our side beyond the cache.
- **Live Trends gives 14 rounds, not 50.** Five years of weekly data per term
  only supports one playable window each once a training region is reserved. The
  builder redistributes the shortfall to the other round types.
- **The crowd layer needs people.** With fewer than 3 drawings on a round the AI
  is model-only and the "beat the crowd" bonus is unavailable. `seed-demo` exists
  precisely because a cold demo has no crowd.
- **The demo cohort is simulated,** including a deliberately modelled shared
  misread (players over-extrapolate the recent slope). Its dashboard numbers
  describe simulated behaviour, not measured human behaviour, until real people
  play.
- **Blend weights are global per round type,** not per round or per player. A
  per-round weight would be better but needs far more drawings per round.
- **The base model is linear.** Ridge on lag features is a strong, fast baseline
  and it is honest about what it is, but it cannot represent regime changes;
  gradient boosting per output would likely help on the stock rounds.
- **Single-process SQLite.** Fine for a demo and a room full of phones; it is not
  a production write path.
