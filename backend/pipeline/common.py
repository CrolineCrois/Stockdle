"""Shared helpers for the TAPE data pipeline.

Every scraper in this package follows the same three-step contract:

1. try the live source,
2. cache whatever it got to ``data/raw/<source>.json``,
3. on *any* failure fall back to ``data/seed/<source>.json``.

Series are passed around as plain dicts so they can be JSON-cached verbatim::

    {
      "source": "electricity",       # electricity | stock | trends
      "key": "ERCOT",                # series identifier within the source
      "unit": "MW",
      "y_label": "Demand (MW)",
      "x_label": "Hour",
      "freq": "hourly",
      "is_seed": True,
      "t": ["2025-07-01T00:00:00", ...],
      "y": [45120.0, ...],
      "aux": {"temp_f": [...]},      # optional aligned covariates
      "meta": {...},                 # region/city/ticker/term ...
      "events": [{"idx": 912, "title": "...", "published": "...", "is_fake": False}],
    }
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

import numpy as np

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
DATA_DIR = Path(os.environ.get("TAPE_DATA_DIR", REPO_ROOT / "data"))
RAW_DIR = DATA_DIR / "raw"
SEED_DIR = DATA_DIR / "seed"
ROUNDS_DIR = DATA_DIR / "rounds"

for _d in (RAW_DIR, SEED_DIR, ROUNDS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# --- Round geometry -------------------------------------------------------
HIDDEN_LEN = 50          # the player always draws exactly 50 y-values
VISIBLE_LEN = 75         # 75 / 125 == 60% of the window is revealed
WINDOW_LEN = VISIBLE_LEN + HIDDEN_LEN
PAD_FRAC = 0.10          # 10% headroom above/below the window's true range


def log(msg: str) -> None:
    print(f"[pipeline] {msg}", flush=True)


def write_json(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=1, default=str), encoding="utf-8")
    tmp.replace(path)
    return path


def read_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def cache_age_hours(path: Path) -> float:
    try:
        return (time.time() - path.stat().st_mtime) / 3600.0
    except OSError:
        return float("inf")


def load_with_fallback(
    source: str,
    live: Callable[[], list[dict]],
    *,
    max_cache_hours: float = 12.0,
    use_live: bool = True,
) -> list[dict]:
    """Run the live/cache/seed ladder for one source and return its series."""
    raw_path = RAW_DIR / f"{source}.json"
    seed_path = SEED_DIR / f"{source}.json"

    cached = read_json(raw_path)
    if cached and cache_age_hours(raw_path) < max_cache_hours:
        log(f"{source}: using cache ({len(cached)} series, "
            f"{cache_age_hours(raw_path):.1f}h old)")
        return cached

    if use_live:
        try:
            series = live()
            if series:
                write_json(raw_path, series)
                log(f"{source}: LIVE ok ({len(series)} series) -> cached")
                return series
            log(f"{source}: live source returned nothing")
        except Exception as exc:  # noqa: BLE001 - the whole point is to never die
            log(f"{source}: live source failed ({type(exc).__name__}: {exc})")
    else:
        log(f"{source}: live fetch disabled")

    if cached:
        log(f"{source}: falling back to stale cache ({len(cached)} series)")
        return cached

    seeded = read_json(seed_path)
    if seeded:
        log(f"{source}: falling back to SEED ({len(seeded)} series)")
        return seeded

    log(f"{source}: no data at all (run `python -m pipeline.seed_gen`)")
    return []


# --- Normalisation --------------------------------------------------------
@dataclass
class Scale:
    """Maps a round's real units onto the 0-1 canvas the player draws on."""

    y_min: float
    y_max: float
    unit: str
    y_label: str

    def to_unit(self, values: Iterable[float]) -> list[float]:
        span = max(self.y_max - self.y_min, 1e-9)
        return [float((v - self.y_min) / span) for v in values]

    def to_real(self, values: Iterable[float]) -> list[float]:
        span = self.y_max - self.y_min
        return [float(self.y_min + v * span) for v in values]

    def as_dict(self) -> dict:
        return {
            "y_min": round(self.y_min, 6),
            "y_max": round(self.y_max, 6),
            "unit": self.unit,
            "y_label": self.y_label,
        }


def make_scale(window: Iterable[float], unit: str, y_label: str) -> Scale:
    arr = np.asarray(list(window), dtype=float)
    lo, hi = float(arr.min()), float(arr.max())
    span = hi - lo
    if span < 1e-9:                      # dead-flat window: invent a little room
        span = max(abs(hi), 1.0) * 0.02
    pad = PAD_FRAC * span
    return Scale(y_min=lo - pad, y_max=hi + pad, unit=unit, y_label=y_label)


def resample(values: Iterable[float], n: int) -> list[float]:
    """Linearly resample a sequence onto exactly ``n`` points."""
    arr = np.asarray(list(values), dtype=float)
    if arr.size == 0:
        return [0.0] * n
    if arr.size == n:
        return [float(v) for v in arr]
    src = np.linspace(0.0, 1.0, arr.size)
    dst = np.linspace(0.0, 1.0, n)
    return [float(v) for v in np.interp(dst, src, arr)]
