"""Cut raw series into game rounds and (disjoint) model training windows.

Output:

* ``data/rounds/rounds.json``  -- the ~200 playable rounds
* ``data/rounds/training.json`` -- a much larger set of historical windows,
  guaranteed not to share a single source index with any game round.

Every round presents 75 visible + exactly 50 hidden points. How many *real*
source steps that spans is per-type (``REAL_GEOMETRY``) and the window is
resampled onto the canvas geometry. Y-values are normalised to 0-1 per round
against the full window's min/max with 10% padding, and the ``scale`` block
carries the inverse map so the canvas can print real units on the axis.

Run with::

    python -m pipeline.build_rounds            # live where possible
    python -m pipeline.build_rounds --offline  # seed/cache only
"""

from __future__ import annotations

import argparse
import hashlib
from datetime import datetime
from typing import Iterable

import numpy as np

from . import electricity, stocks, trends
from .common import (
    HIDDEN_LEN,
    resample,
    ROUNDS_DIR,
    VISIBLE_LEN,
    WINDOW_LEN,
    log,
    make_scale,
    write_json,
)
from .fake_headlines import get_fake_templates

# Target catalogue size. The per-type split is *not* fixed: it is allocated
# from how many non-overlapping windows each source can actually supply, so a
# thin source does not shrink the catalogue. This matters live — Google Trends
# only serves 5 years at weekly resolution (260 points), which fits a single
# 125-step window per term, while the seed archive carries 14 years.
TARGET_ROUNDS = 200
MIN_PER_TYPE = 12                 # every type must still show up in the mix
# The catalogue the game advertises. Fake rounds are the smallest slice on
# purpose: they are a twist, and stop landing as one if every other round is one.
DESIRED_MIX = {"electricity": 0.30, "stock": 0.26, "trends": 0.24, "fake_stock": 0.20}
MIX_STRETCH = 1.6                 # a type may absorb at most 1.6x its share
GAME_QUOTA = {"electricity": 60, "stock": 50, "trends": 50, "fake_stock": 50}
# Dense stride for training windows, per source. Training windows may overlap
# each other (that is normal for sliding-window forecasting) but never a round.
TRAIN_STRIDE = {"electricity": 4, "stock": 23, "trends": 2}
TRAIN_CAP = 2600                  # per source, keeps `train.py` snappy

# How many *real source steps* a window spans, per type, before being resampled
# onto the canvas fixed 75 visible + 50 hidden points.
#
# Hourly and minute data have history to spare, so they use the canvas geometry
# directly. Weekly search interest does not: Google Trends serves 5 years (260
# weeks) at weekly resolution, and a 125-week window fits twice into that,
# leaving almost nothing to train on. A 60-week run-up predicting 26 weeks ahead
# is both a better puzzle (half a year, not two) and leaves most of the series
# free for training windows.
REAL_GEOMETRY = {
    "electricity": (VISIBLE_LEN, HIDDEN_LEN),
    "stock": (VISIBLE_LEN, HIDDEN_LEN),
    "fake_stock": (VISIBLE_LEN, HIDDEN_LEN),
    "trends": (60, 26),
}


def geom(kind: str) -> tuple[int, int, int]:
    """Return (visible_steps, hidden_steps, window_steps) in real source steps."""
    vis, hid = REAL_GEOMETRY.get(kind, (VISIBLE_LEN, HIDDEN_LEN))
    return vis, hid, vis + hid


# Fraction of each series held back from game rounds so training windows have a
# contiguous region to slide over. Game rounds are cut from the tail (the most
# recent, most interesting data); the model learns from the head.
#
# This matters most where history is short: live Google Trends gives 3 windows
# per term, and without a reserve all three become game rounds and the trends
# forecaster has zero training data.
# 0.67 for trends means: with live data (3 windows per term) only the most
# recent window becomes a round and the other two train the model; with the
# 14-year seed archive (8 windows) the last three become rounds.
GAME_REGION_START = {"electricity": 0.25, "trends": 0.55}

# Trends rounds are chosen for playability, not on a fixed grid: candidate cuts
# are scanned every TRENDS_PICK_STRIDE weeks and kept only when at least
# TRENDS_MIN_ACTION of the window's range falls in the half the player must draw.
TRENDS_PICK_STRIDE = 2
TRENDS_MIN_ACTION = 0.25

QUIET_GUARD = 180                 # steps a fake round must keep clear of real news

DOW = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


# --- window helpers -------------------------------------------------------
def _norm_window(window: Iterable[float], unit: str, y_label: str):
    scale = make_scale(window, unit, y_label)
    unitised = scale.to_unit(window)
    return unitised[:VISIBLE_LEN], unitised[VISIBLE_LEN:], scale


def _round_id(kind: str, key: str, cut: int) -> str:
    stamp = hashlib.sha1(f"{kind}|{key}|{cut}".encode()).hexdigest()[:8]
    return f"{kind}_{stamp}"


class IndexReservation:
    """Tracks which source indices a game round consumed, per series key."""

    def __init__(self) -> None:
        self._spans: dict[str, list[tuple[int, int]]] = {}

    def reserve(self, key: str, lo: int, hi: int) -> None:
        self._spans.setdefault(key, []).append((lo, hi))

    def free(self, key: str, lo: int, hi: int) -> bool:
        return all(hi <= s or lo >= e for s, e in self._spans.get(key, ()))


# --- context builders -----------------------------------------------------
def _electricity_context(series: dict, cut: int, window_temps: list[float]):
    stamp = datetime.fromisoformat(series["t"][cut])
    forecast_high = max(window_temps[VISIBLE_LEN:]) if window_temps else None
    temp_now = window_temps[VISIBLE_LEN - 1] if window_temps else None
    bits = [f"Region: {series['meta'].get('region', series['key'])}"]
    if forecast_high is not None:
        bits.append(f"Forecast high {forecast_high:.0f}°F")
    bits.append(DOW[stamp.weekday()])
    context = {
        "kind": "electricity",
        "eyebrow": "Grid demand",
        "title": " · ".join(bits),
        "subtitle": f"{series['meta'].get('city', '')} · cut at "
                    f"{stamp.strftime('%H:%M')} · next 50 hours hidden",
        "chips": [series["meta"].get("region", series["key"]),
                  f"{temp_now:.0f}°F now" if temp_now is not None else "no temp data"],
    }
    reveal = {
        "region": series["meta"].get("region", series["key"]),
        "city": series["meta"].get("city"),
        "cut_at": stamp.isoformat(),
        "forecast_high_f": round(forecast_high, 1) if forecast_high is not None else None,
    }
    feat = {
        "hour": stamp.hour,
        "dow": stamp.weekday(),
        "month": stamp.month,
        "temp_now": float(temp_now) if temp_now is not None else 70.0,
        "temp_hi": float(forecast_high) if forecast_high is not None else 70.0,
        "temp_lo": float(min(window_temps[VISIBLE_LEN:])) if window_temps else 70.0,
        "temp_mean_vis": float(np.mean(window_temps[:VISIBLE_LEN])) if window_temps else 70.0,
    }
    return context, reveal, feat


def _stock_context(series: dict, cut: int, headline: str | None, *,
                   is_fake: bool, publisher: str | None, age_steps: int):
    stamp = datetime.fromisoformat(series["t"][cut])
    context = {
        "kind": "fake_stock" if is_fake else "stock",
        "eyebrow": "Mystery stock",
        "title": headline or "No news — just the tape",
        "subtitle": "Ticker and date revealed after you draw",
        "headline": headline,
        "is_fake": is_fake,
        "publisher": publisher,
        "chips": ["Mystery stock", f"{series['freq']} bars"],
    }
    reveal = {
        "ticker": series["meta"].get("ticker", series["key"]),
        "name": series["meta"].get("name"),
        "date": stamp.date().isoformat(),
        "cut_at": stamp.isoformat(),
        "headline": headline,
        "is_fake": is_fake,
        "publisher": publisher,
    }
    feat = {"headline": headline or "", "is_fake": is_fake, "age_steps": age_steps,
            "hour": stamp.hour, "dow": stamp.weekday()}
    return context, reveal, feat


def _trends_context(series: dict, cut: int):
    stamp = datetime.fromisoformat(series["t"][cut])
    term = series["meta"].get("term", series["key"])
    context = {
        "kind": "trends",
        "eyebrow": "Google Trends",
        "title": f"“{term}”",
        "subtitle": "Weekly US search interest · next "
                    f"{REAL_GEOMETRY['trends'][1]} weeks hidden",
        "chips": [term, stamp.strftime("%b %Y")],
    }
    reveal = {"term": term, "geo": series["meta"].get("geo", "US"),
              "cut_at": stamp.date().isoformat()}
    feat = {"week": stamp.isocalendar().week, "month": stamp.month}
    return context, reveal, feat


# --- per-source cutters ---------------------------------------------------
def _make_record(kind: str, series: dict, cut: int, *, context, reveal, feat,
                 is_fake: bool, is_game: bool) -> dict | None:
    """Build one round/window with its cut *after* index ``cut``."""
    vis_n, hid_n, _ = geom(kind)
    start = cut - vis_n + 1
    end = cut + 1 + hid_n
    if start < 0 or end > len(series["y"]):
        return None
    raw = series["y"][start:end]
    # Resample each half independently so the cut stays exactly on the boundary
    # between the 75th visible point and the 1st hidden one.
    window = resample(raw[:vis_n], VISIBLE_LEN) + resample(raw[vis_n:], HIDDEN_LEN)
    visible, hidden, scale = _norm_window(window, series["unit"], series["y_label"])
    if len(hidden) != HIDDEN_LEN:
        return None
    rec = {
        "id": _round_id(kind, series["key"], cut),
        "type": kind,
        "source_key": series["key"],
        "visible": [round(v, 6) for v in visible],
        "hidden": [round(v, 6) for v in hidden],
        "context": context,
        "reveal_info": reveal,
        "is_fake": is_fake,
        "is_seed": bool(series.get("is_seed")),
        "scale": scale.as_dict(),
        "x_label": series.get("x_label", "Step"),
        "feat": feat,
        "span": [start, end],
    }
    if not is_game:
        rec.pop("context")
        rec.pop("reveal_info")
    return rec


def cut_electricity(series_list: list[dict], res: IndexReservation, rng,
                    quota: int | None = None):
    games, trains = [], []
    quota = GAME_QUOTA["electricity"] if quota is None else quota
    quota_each = max(1, quota // max(1, len(series_list)))
    vis_n, hid_n, win = geom("electricity")
    for s in series_list:
        n = len(s["y"])
        temps = s.get("aux", {}).get("temp_f") or []
        n_blocks = n // win
        if n_blocks < 1:
            continue
        # Spread game rounds across the tail of history; the head trains.
        lo_block = int(n_blocks * GAME_REGION_START["electricity"])
        picks = np.linspace(lo_block, n_blocks - 1, min(quota_each, n_blocks - lo_block))
        for b in sorted({int(round(p)) for p in picks}):
            cut = b * win + vis_n - 1
            win_temps = temps[cut - vis_n + 1: cut + 1 + hid_n]
            ctx, rev, feat = _electricity_context(s, cut, win_temps)
            rec = _make_record("electricity", s, cut, context=ctx, reveal=rev,
                               feat=feat, is_fake=False, is_game=True)
            if rec:
                games.append(rec)
                res.reserve(s["key"], rec["span"][0], rec["span"][1])

        stride = TRAIN_STRIDE["electricity"]
        for cut in range(vis_n - 1, n - hid_n - 1, stride):
            start, end = cut - vis_n + 1, cut + 1 + hid_n
            if not res.free(s["key"], start, end):
                continue
            win_temps = temps[start:end]
            _, _, feat = _electricity_context(s, cut, win_temps)
            rec = _make_record("electricity", s, cut, context=None, reveal=None,
                               feat=feat, is_fake=False, is_game=False)
            if rec:
                trains.append(rec)
    return games, trains


def cut_stocks(series_list: list[dict], res: IndexReservation, rng,
               quota: int | None = None, fake_quota: int | None = None):
    games, fakes, trains = [], [], []
    quota = GAME_QUOTA["stock"] if quota is None else quota
    fake_quota = GAME_QUOTA["fake_stock"] if fake_quota is None else fake_quota
    fake_pool = get_fake_templates()

    # 1. Real-headline rounds: cut exactly at the publish bar.
    candidates = []
    vis_n, hid_n, win = geom("stock")
    for s in series_list:
        for ev in s.get("events", []):
            cut = int(ev["idx"])
            if cut - vis_n + 1 < 0 or cut + 1 + hid_n > len(s["y"]):
                continue
            candidates.append((s, ev, cut))
    rng.shuffle(candidates)
    for s, ev, cut in candidates[:quota]:
        ctx, rev, feat = _stock_context(s, cut, ev["title"], is_fake=False,
                                        publisher=ev.get("publisher"), age_steps=0)
        rec = _make_record("stock", s, cut, context=ctx, reveal=rev, feat=feat,
                           is_fake=False, is_game=True)
        if rec:
            games.append(rec)
            res.reserve(s["key"], rec["span"][0], rec["span"][1])

    # 2. Fake-headline rounds: cut somewhere quiet, so the truth is a non-reaction.
    per_series = max(1, fake_quota // max(1, len(series_list)))
    for s in series_list:
        n = len(s["y"])
        ev_idx = [int(e["idx"]) for e in s.get("events", [])]
        placed = 0
        starts = list(range(vis_n - 1, n - hid_n - 1, win))
        rng.shuffle(starts)
        for cut in starts:
            if placed >= per_series:
                break
            start, end = cut - vis_n + 1, cut + 1 + hid_n
            if not res.free(s["key"], start, end):
                continue
            if any(abs(cut - e) < QUIET_GUARD for e in ev_idx):
                continue
            headline = fake_pool[int(rng.integers(len(fake_pool)))].format(
                name=s["meta"].get("name", s["key"]), ticker=s["key"])
            ctx, rev, feat = _stock_context(s, cut, headline, is_fake=True,
                                            publisher="Fabricated for this game",
                                            age_steps=0)
            rec = _make_record("fake_stock", s, cut, context=ctx, reveal=rev,
                               feat=feat, is_fake=True, is_game=True)
            if rec:
                fakes.append(rec)
                res.reserve(s["key"], rec["span"][0], rec["span"][1])
                placed += 1

    # 3. Training windows: dense, with the most recent real headline as context.
    stride = TRAIN_STRIDE["stock"]
    for s in series_list:
        n = len(s["y"])
        ev_sorted = sorted(((int(e["idx"]), e) for e in s.get("events", [])),
                           key=lambda p: p[0])
        for cut in range(vis_n - 1, n - hid_n - 1, stride):
            start, end = cut - vis_n + 1, cut + 1 + hid_n
            if not res.free(s["key"], start, end):
                continue
            headline, age = "", 999
            for idx, ev in ev_sorted:
                if idx <= cut and cut - idx < 240:
                    headline, age = ev["title"], cut - idx
            _, _, feat = _stock_context(s, cut, headline or None, is_fake=False,
                                        publisher=None, age_steps=age)
            rec = _make_record("stock", s, cut, context=None, reveal=None,
                               feat=feat, is_fake=False, is_game=False)
            if rec:
                trains.append(rec)
    return games, fakes, trains


def cut_trends(series_list: list[dict], res: IndexReservation, rng,
               quota: int | None = None):
    games, trains = [], []
    quota = GAME_QUOTA["trends"] if quota is None else quota
    quota_each = max(1, quota // max(1, len(series_list)))
    vis_n, hid_n, win = geom("trends")
    for s in series_list:
        n = len(s["y"])
        if n < win:
            continue
        y = np.asarray(s["y"], dtype=float)

        # Slide over the game region (the recent tail) and score every candidate
        # cut by how much of the window's total range lives in the hidden half.
        # A score near 1 means the season is still to come -- a real puzzle. A
        # score near 0 means the spike already happened in the visible run-up and
        # the player would be drawing a flat line.
        lo_cut = max(vis_n - 1, int(n * GAME_REGION_START["trends"]) + vis_n - 1)
        scored: list[tuple[float, int]] = []
        for cut in range(lo_cut, n - hid_n, TRENDS_PICK_STRIDE):
            window = y[cut - vis_n + 1: cut + 1 + hid_n]
            hidden = y[cut + 1: cut + 1 + hid_n]
            span = float(window.max() - window.min())
            if span <= 1e-9 or len(hidden) < hid_n:
                continue
            scored.append((float(hidden.max() - hidden.min()) / span, cut))
        scored.sort(key=lambda p: -p[0])

        taken: list[tuple[int, int]] = []
        for score, cut in scored:
            if len(taken) >= quota_each:
                break
            if score < TRENDS_MIN_ACTION:
                break
            start, end = cut - vis_n + 1, cut + 1 + hid_n
            if any(not (end <= a or start >= b) for a, b in taken):
                continue
            ctx, rev, feat = _trends_context(s, cut)
            ctx = {**ctx, "chips": [*ctx["chips"], f"{score:.0%} of the action ahead"]}
            rec = _make_record("trends", s, cut, context=ctx, reveal=rev,
                               feat=feat, is_fake=False, is_game=True)
            if rec:
                games.append(rec)
                taken.append((start, end))
                res.reserve(s["key"], start, end)

        for cut in range(vis_n - 1, n - hid_n - 1, TRAIN_STRIDE["trends"]):
            start, end = cut - vis_n + 1, cut + 1 + hid_n
            if not res.free(s["key"], start, end):
                continue
            _, _, feat = _trends_context(s, cut)
            rec = _make_record("trends", s, cut, context=None, reveal=None,
                               feat=feat, is_fake=False, is_game=False)
            if rec:
                trains.append(rec)
    return games, trains


# --- quota allocation -----------------------------------------------------
def _block_capacity(series_list: list[dict], kind: str, lo_frac: float = 0.0) -> int:
    """How many non-overlapping windows a source can supply."""
    _, _, win = geom(kind)
    total = 0
    for s in series_list:
        # Count windows that fit in the *game region* only. Measuring it as a
        # fraction of the block count instead over-reports on short series and
        # makes the allocator budget rounds the cutter cannot deliver.
        region = len(s["y"]) - int(len(s["y"]) * lo_frac)
        total += max(0, region // win)
    return total


def capacities(elec: list[dict], stk: list[dict], trd: list[dict]) -> dict[str, int]:
    vis_n, hid_n, _ = geom("stock")
    usable_events = sum(
        1
        for s in stk
        for ev in (s.get("events") or [])
        if vis_n - 1 <= int(ev["idx"]) <= len(s["y"]) - hid_n - 1
    )
    return {
        "electricity": _block_capacity(elec, "electricity",
                                       GAME_REGION_START["electricity"]),
        "stock": usable_events,
        # Fake rounds need quiet blocks, and compete with real-headline rounds
        # for the same series, so budget conservatively.
        "fake_stock": max(0, _block_capacity(stk, "stock") - usable_events),
        "trends": _block_capacity(trd, "trends", GAME_REGION_START["trends"]),
    }


def allocate(caps: dict[str, int], target: int = TARGET_ROUNDS) -> dict[str, int]:
    """Split ``target`` rounds across types, bounded by what each can supply.

    Three constraints at once:

    * **capacity** — never ask a source for more windows than it has;
    * **the intended mix** (``DESIRED_MIX``) — the catalogue should feel like
      the game it advertises, not like whichever source happened to be biggest;
    * **a ceiling** of ``MIX_STRETCH`` x the intended share, so redistributing a
      thin source's shortfall cannot let one type swamp the catalogue. Fake
      rounds have effectively unlimited capacity (any quiet window will do), so
      without this they would take everything going.

    Shortfall is redistributed by intended share, among types that still have
    both capacity and headroom.
    """
    quota = {k: 0 for k in caps}
    ceiling = {
        k: min(caps[k], int(round(target * DESIRED_MIX.get(k, 0.25) * MIX_STRETCH)))
        for k in caps
    }
    for k in caps:
        want = int(round(target * DESIRED_MIX.get(k, 0.25)))
        quota[k] = min(caps[k], max(min(MIN_PER_TYPE, caps[k]), min(want, ceiling[k])))

    remaining = target - sum(quota.values())
    while remaining > 0:
        room = {k: ceiling[k] - quota[k] for k in caps if ceiling[k] > quota[k]}
        if not room:
            break
        weight = sum(DESIRED_MIX.get(k, 0.25) for k in room)
        handed = 0
        for k in sorted(room, key=lambda x: -room[x]):
            share = min(
                room[k],
                max(1, round(remaining * DESIRED_MIX.get(k, 0.25) / weight)),
                remaining - handed,
            )
            quota[k] += share
            handed += share
            if handed >= remaining:
                break
        if handed == 0:
            break
        remaining -= handed

    # Over-target can happen when every type's intended share rounds up.
    overflow = sum(quota.values()) - target
    for k in sorted(quota, key=lambda x: -(quota[x] - MIN_PER_TYPE)):
        if overflow <= 0:
            break
        give = min(overflow, max(0, quota[k] - MIN_PER_TYPE))
        quota[k] -= give
        overflow -= give
    return quota


def _cap(items: list[dict], cap: int, rng) -> list[dict]:
    if len(items) <= cap:
        return items
    keep = rng.choice(len(items), size=cap, replace=False)
    return [items[i] for i in sorted(keep)]


def build(use_live: bool = True, seed: int = 7) -> dict:
    rng = np.random.default_rng(seed)
    res = IndexReservation()

    elec = electricity.load(use_live=use_live)
    stk = stocks.load(use_live=use_live)
    trd = trends.load(use_live=use_live)

    caps = capacities(elec, stk, trd)
    quota = allocate(caps)
    log(f"capacity {caps} -> quota {quota}")

    e_games, e_train = cut_electricity(elec, res, rng, quota["electricity"])
    s_games, f_games, s_train = cut_stocks(stk, res, rng, quota["stock"],
                                           quota["fake_stock"])
    t_games, t_train = cut_trends(trd, res, rng, quota["trends"])

    rounds = e_games + s_games + f_games + t_games
    rng.shuffle(rounds)
    training = (_cap(e_train, TRAIN_CAP, rng) + _cap(s_train, TRAIN_CAP, rng)
                + _cap(t_train, TRAIN_CAP, rng))

    # Guarantee the no-overlap invariant actually holds before we ship it.
    spans: dict[str, list[tuple[int, int]]] = {}
    for r in rounds:
        spans.setdefault(r["source_key"], []).append(tuple(r["span"]))
    clashes = sum(
        1 for w in training
        for lo, hi in spans.get(w["source_key"], ())
        if not (w["span"][1] <= lo or w["span"][0] >= hi)
    )
    assert clashes == 0, f"{clashes} training windows overlap a game round"

    write_json(ROUNDS_DIR / "rounds.json", rounds)
    write_json(ROUNDS_DIR / "training.json", training)

    by_type: dict[str, int] = {}
    for r in rounds:
        by_type[r["type"]] = by_type.get(r["type"], 0) + 1
    train_by_type: dict[str, int] = {}
    for w in training:
        train_by_type[w["type"]] = train_by_type.get(w["type"], 0) + 1

    summary = {
        "rounds": len(rounds), "rounds_by_type": by_type,
        "training": len(training), "training_by_type": train_by_type,
        "seed_sources": sorted({s["source"] for s in (elec + stk + trd) if s["is_seed"]}),
        "live_sources": sorted({s["source"] for s in (elec + stk + trd) if not s["is_seed"]}),
        "overlap_clashes": clashes,
        "capacity": caps,
        "quota": quota,
        "built_at": datetime.now().isoformat(timespec="seconds"),
    }
    write_json(ROUNDS_DIR / "summary.json", summary)
    log(f"built {len(rounds)} rounds {by_type}")
    log(f"built {len(training)} training windows {train_by_type}")
    return summary


def export_safe(round_rec: dict) -> dict:
    """A round stripped of anything that must not leave the app.

    Drops ``hidden`` (the answer) and replaces fabricated headline text with a
    neutral label, so exports can never carry a fake headline as plain text.
    """
    out = {k: v for k, v in round_rec.items() if k not in ("hidden", "feat", "span")}
    if round_rec.get("is_fake"):
        for block in ("context", "reveal_info"):
            if isinstance(out.get(block), dict):
                out[block] = {**out[block],
                              "headline": "[fabricated headline withheld]",
                              "title": "[fabricated headline withheld]"}
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true",
                    help="skip live sources; use cache/seed only")
    args = ap.parse_args()
    import json as _json
    print(_json.dumps(build(use_live=not args.offline), indent=2))
