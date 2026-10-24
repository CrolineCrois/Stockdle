"""Generate bundled fallback data for every source.

The output lands in ``data/seed/*.json`` and is checked into the repo so the
whole game runs with no network and no API keys. Everything produced here is
flagged ``is_seed: True`` and carries a ``synthetic`` note in ``meta`` -- the UI
shows a "seed data" chip for those rounds so nobody mistakes it for real
history.

The shapes are modelled on the real sources rather than being pure noise:
hourly load curves with a morning shoulder and a temperature-driven evening
peak, intraday prices as jump-diffusion with headline-reactive drift, and
weekly search interest with a seasonal bump around each term's season.

Run with::

    python -m pipeline.seed_gen
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np

from .common import SEED_DIR, log, write_json

MASTER_SEED = 20261024

# --- 1. Electricity demand (EIA-930 shaped) -------------------------------
REGIONS = [
    {"ba": "ERCOT", "city": "Dallas, TX", "tz": "America/Chicago", "lat": 32.78, "lon": -96.80,
     "base_mw": 38000, "cool": 1450, "heat": 620, "t_mean": 78, "t_amp": 16},
    {"ba": "PJM", "city": "Philadelphia, PA", "tz": "America/New_York", "lat": 39.95, "lon": -75.17,
     "base_mw": 78000, "cool": 1900, "heat": 1350, "t_mean": 62, "t_amp": 21},
    {"ba": "CAISO", "city": "Los Angeles, CA", "tz": "America/Los_Angeles", "lat": 34.05, "lon": -118.24,
     "base_mw": 24000, "cool": 780, "heat": 290, "t_mean": 68, "t_amp": 10},
]

# Hour-of-day multiplicative load shape: overnight trough, morning shoulder,
# evening ramp into the 18:00-19:00 peak.
HOUR_SHAPE = np.array([
    0.84, 0.81, 0.79, 0.78, 0.79, 0.83, 0.89, 0.94, 0.96, 0.96, 0.96, 0.97,
    0.98, 1.00, 1.02, 1.05, 1.08, 1.11, 1.12, 1.09, 1.04, 0.98, 0.92, 0.87,
])


def _gen_electricity(rng: np.random.Generator, days: int = 150) -> list[dict]:
    series = []
    end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(days=days)

    for reg in REGIONS:
        n = days * 24
        stamps = [start + timedelta(hours=i) for i in range(n)]
        # Stamps are UTC; daily rhythms (load shape, the afternoon temperature
        # peak, weekends) follow the region's local clock.
        local = [s.astimezone(ZoneInfo(reg["tz"])) for s in stamps]
        doy = np.array([s.timetuple().tm_yday for s in local], dtype=float)
        hod = np.array([s.hour for s in local], dtype=float)
        dow = np.array([s.weekday() for s in local], dtype=float)

        # Temperature: annual sinusoid + diurnal swing + mean-reverting weather.
        # An AR(1) anomaly (std ~4°F, decorrelates over ~1.5 days) gives heat
        # waves and cold snaps without the unbounded drift of a random walk.
        annual = reg["t_mean"] + reg["t_amp"] * np.sin(2 * np.pi * (doy - 196) / 365.25)
        diurnal = 9.0 * np.sin(2 * np.pi * (hod - 9) / 24.0)
        shocks = rng.normal(0, 0.95, n)
        weather = np.zeros(n)
        for i in range(1, n):
            weather[i] = 0.97 * weather[i - 1] + shocks[i]
        temp_f = annual + diurnal + weather + rng.normal(0, 1.1, n)

        cdd = np.clip(temp_f - 68.0, 0, None)
        hdd = np.clip(58.0 - temp_f, 0, None)
        weekend = np.where(dow >= 5, 0.93, 1.0)

        load = (
            reg["base_mw"] + reg["cool"] * cdd + reg["heat"] * hdd
        ) * HOUR_SHAPE[hod.astype(int)] * weekend
        # Hot afternoons amplify the evening peak beyond the flat shape.
        load *= 1.0 + 0.0022 * cdd * np.clip(np.sin(np.pi * (hod - 11) / 11.0), 0, None)
        load += np.cumsum(rng.normal(0, 90, n)) * 0.18
        load += rng.normal(0, reg["base_mw"] * 0.004, n)

        series.append({
            "source": "electricity",
            "key": reg["ba"],
            "unit": "MW",
            "y_label": "Demand (MW)",
            "x_label": "Hour",
            "freq": "hourly",
            "is_seed": True,
            "t": [s.isoformat() for s in stamps],
            "y": [round(float(v), 1) for v in load],
            "aux": {"temp_f": [round(float(v), 1) for v in temp_f]},
            "meta": {
                "region": reg["ba"], "city": reg["city"], "tz": reg["tz"],
                "lat": reg["lat"], "lon": reg["lon"],
                "synthetic": "load curve modelled on EIA-930 shape",
            },
            "events": [],
        })
    return series


# --- 2. Stocks + headlines ------------------------------------------------
TICKERS = [
    {"t": "AAPL", "name": "Apple", "px": 228.0, "vol": 0.013},
    {"t": "MSFT", "name": "Microsoft", "px": 418.0, "vol": 0.012},
    {"t": "NVDA", "name": "Nvidia", "px": 139.0, "vol": 0.028},
    {"t": "TSLA", "name": "Tesla", "px": 247.0, "vol": 0.031},
    {"t": "AMZN", "name": "Amazon", "px": 186.0, "vol": 0.016},
    {"t": "GOOGL", "name": "Alphabet", "px": 171.0, "vol": 0.015},
    {"t": "META", "name": "Meta", "px": 576.0, "vol": 0.019},
    {"t": "AMD", "name": "AMD", "px": 152.0, "vol": 0.026},
    {"t": "COIN", "name": "Coinbase", "px": 198.0, "vol": 0.038},
    {"t": "JPM", "name": "JPMorgan", "px": 221.0, "vol": 0.011},
    {"t": "DIS", "name": "Disney", "px": 96.0, "vol": 0.017},
    {"t": "UBER", "name": "Uber", "px": 78.0, "vol": 0.021},
]

# (template, drift sign) -- drift is what the seed *price* actually does after
# the headline, so the data carries a learnable (but noisy) headline->move signal.
REAL_HEADLINES = [
    ("{name} beats quarterly estimates, raises full-year guidance", +1),
    ("{name} tops revenue expectations as margins expand", +1),
    ("Analysts lift {ticker} price target after strong product cycle", +1),
    ("{name} announces $10B buyback expansion", +1),
    ("{name} lands multi-year cloud contract with federal agency", +1),
    ("{name} misses on earnings, cuts outlook for the quarter", -1),
    ("{name} warns of softening demand heading into the holidays", -1),
    ("Regulators open inquiry into advertising practices at {name}", -1),
    ("{name} supply chain disruption delays flagship launch", -1),
    ("Short seller publishes critical report on {ticker}", -1),
    ("{name} holds annual developer conference", 0),
    ("{name} names new chief financial officer", 0),
    ("{ticker} added to sector index in quarterly rebalance", 0),
    ("{name} to present at industry summit next week", 0),
]


def _gen_stocks(rng: np.random.Generator, days: int = 24) -> list[dict]:
    series = []
    bars_per_day = 390                                    # 1-minute US session
    today = datetime.now(timezone.utc).replace(hour=13, minute=30, second=0,
                                               microsecond=0)
    for tk in TICKERS:
        stamps: list[datetime] = []
        px: list[float] = []
        price = tk["px"]
        day_cursor = today - timedelta(days=days + 12)
        sessions = 0
        while sessions < days:
            day_cursor += timedelta(days=1)
            if day_cursor.weekday() >= 5:
                continue
            sessions += 1
            price *= 1.0 + rng.normal(0, tk["vol"] * 0.55)            # overnight gap
            minute_vol = tk["vol"] / np.sqrt(bars_per_day)
            # U-shaped intraday volatility: busy open and close.
            idx = np.arange(bars_per_day)
            prof = (1.0 + 0.9 * np.exp(-idx / 45.0)
                        + 0.7 * np.exp(-(bars_per_day - 1 - idx) / 40.0))
            steps = rng.normal(0, minute_vol, bars_per_day) * prof
            steps += rng.normal(0, tk["vol"] * 0.12) / bars_per_day    # session drift
            if rng.random() < 0.22:                                    # intraday jump
                steps[rng.integers(30, bars_per_day - 30)] += rng.normal(0, tk["vol"] * 0.8)
            path = price * np.cumprod(1.0 + steps)
            for i, p in enumerate(path):
                stamps.append(day_cursor + timedelta(minutes=i))
                px.append(float(p))
            price = float(path[-1])

        y = np.asarray(px)
        events = []
        for _ in range(int(rng.integers(5, 9))):
            # Place headlines well inside the series so a full window fits.
            at = int(rng.integers(400, len(y) - 260))
            tmpl, sign = REAL_HEADLINES[int(rng.integers(len(REAL_HEADLINES)))]
            mag = abs(rng.normal(0.9, 0.5)) * tk["vol"]
            if sign == 0:
                mag *= 0.25
            drift = sign * mag
            # Price reacts over the ~90 minutes after the headline, then holds.
            horizon = min(170, len(y) - at - 1)
            ramp_len = min(90, horizon)
            ramp = np.concatenate([np.linspace(0, 1, ramp_len),
                                   np.ones(horizon - ramp_len)])
            y[at + 1: at + 1 + horizon] *= 1.0 + drift * ramp
            y[at + 1 + horizon:] *= 1.0 + drift
            events.append({
                "idx": at,
                "title": tmpl.format(name=tk["name"], ticker=tk["t"]),
                "published": stamps[at].isoformat(),
                "publisher": "Seed Newswire",
            })

        series.append({
            "source": "stock",
            "key": tk["t"],
            "unit": "$",
            "y_label": "Price ($)",
            "x_label": "Minutes",
            "freq": "1m",
            "is_seed": True,
            "t": [s.isoformat() for s in stamps],
            "y": [round(float(v), 4) for v in y],
            "aux": {},
            "meta": {"ticker": tk["t"], "name": tk["name"],
                     "synthetic": "jump-diffusion path with headline-reactive drift"},
            "events": sorted(events, key=lambda e: e["idx"]),
        })
    return series


# --- 3. Google Trends -----------------------------------------------------
TREND_TERMS = [
    {"term": "pumpkin spice", "peak_week": 40, "width": 4.0, "amp": 85, "base": 6, "trend": 0.03},
    {"term": "flu symptoms", "peak_week": 3, "width": 7.0, "amp": 70, "base": 14, "trend": 0.0},
    {"term": "sunscreen", "peak_week": 27, "width": 9.0, "amp": 62, "base": 22, "trend": 0.05},
    {"term": "world cup", "peak_week": 48, "width": 2.5, "amp": 92, "base": 5, "trend": 0.0},
    {"term": "tax extension", "peak_week": 15, "width": 2.0, "amp": 88, "base": 4, "trend": 0.01},
    {"term": "air fryer recipes", "peak_week": 2, "width": 6.0, "amp": 45, "base": 30, "trend": 0.12},
    {"term": "halloween costumes", "peak_week": 43, "width": 2.2, "amp": 95, "base": 2, "trend": 0.0},
    {"term": "ski resorts", "peak_week": 52, "width": 6.0, "amp": 58, "base": 12, "trend": -0.02},
    {"term": "allergy medicine", "peak_week": 18, "width": 6.5, "amp": 55, "base": 25, "trend": 0.0},
    {"term": "ice cream near me", "peak_week": 28, "width": 8.0, "amp": 66, "base": 18, "trend": 0.02},
    {"term": "super bowl recipes", "peak_week": 6, "width": 1.6, "amp": 90, "base": 3, "trend": 0.0},
    {"term": "spring cleaning", "peak_week": 13, "width": 4.5, "amp": 48, "base": 16, "trend": -0.01},
    {"term": "black friday deals", "peak_week": 47, "width": 1.8, "amp": 97, "base": 2, "trend": 0.04},
    {"term": "new year resolutions", "peak_week": 1, "width": 1.5, "amp": 93, "base": 3, "trend": -0.03},
]


def _gen_trends(rng: np.random.Generator, years: int = 14) -> list[dict]:
    series = []
    n = years * 52
    end = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    end -= timedelta(days=end.weekday())
    stamps = [end - timedelta(weeks=(n - 1 - i)) for i in range(n)]
    woy = np.array([s.isocalendar().week for s in stamps], dtype=float)
    year_idx = np.array([s.year for s in stamps])

    for spec in TREND_TERMS:
        # Wrapped Gaussian bump so the season stays continuous across new year.
        d = np.abs(woy - spec["peak_week"])
        d = np.minimum(d, 52 - d)
        seasonal = spec["amp"] * np.exp(-0.5 * (d / spec["width"]) ** 2)
        # Year-to-year intensity varies; some seasons are bigger than others.
        for yr in np.unique(year_idx):
            seasonal[year_idx == yr] *= float(rng.normal(1.0, 0.12))
        drift = spec["trend"] * np.arange(n)
        noise = rng.normal(0, 2.6, n) + np.cumsum(rng.normal(0, 0.35, n)) * 0.4
        val = np.clip(spec["base"] + seasonal + drift + noise, 0, None)
        val = np.round(val / max(val.max(), 1e-6) * 100.0, 0)   # Trends rescales to 100

        series.append({
            "source": "trends",
            "key": spec["term"],
            "unit": "",
            "y_label": "Search interest",
            "x_label": "Weeks",
            "freq": "weekly",
            "is_seed": True,
            "t": [s.date().isoformat() for s in stamps],
            "y": [float(v) for v in val],
            "aux": {},
            "meta": {"term": spec["term"], "geo": "US",
                     "synthetic": "wrapped-Gaussian season + drift + noise"},
            "events": [],
        })
    return series


def generate_all(seed: int = MASTER_SEED) -> dict[str, int]:
    counts: dict[str, int] = {}
    for name, fn in (("electricity", _gen_electricity),
                     ("stock", _gen_stocks),
                     ("trends", _gen_trends)):
        rng = np.random.default_rng(seed + sum(map(ord, name)))
        data = fn(rng)
        write_json(SEED_DIR / f"{name}.json", data)
        pts = sum(len(s["y"]) for s in data)
        counts[name] = pts
        log(f"seed {name}: {len(data)} series, {pts:,} points")
    return counts


if __name__ == "__main__":
    generate_all()
