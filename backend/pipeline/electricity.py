"""Live electricity demand: EIA Open Data API v2 + Open-Meteo temperatures.

Hourly demand ("D") per balancing authority from the EIA-930 dataset, joined to
hourly temperature for a representative city from the Open-Meteo historical
archive (free, no key). Needs ``EIA_API_KEY``; without it the loader goes
straight to the cache/seed ladder.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import requests

from .common import load_with_fallback, log
from .seed_gen import REGIONS

EIA_URL = "https://api.eia.gov/v2/electricity/rto/region-data/data/"
METEO_URL = "https://archive-api.open-meteo.com/v1/archive"
# EIA respondent code per balancing authority.
EIA_RESPONDENT = {"ERCOT": "ERCO", "PJM": "PJM", "CAISO": "CISO"}
LOOKBACK_DAYS = 120
TIMEOUT = 25


def _fetch_eia_demand(respondent: str, start: datetime, end: datetime) -> dict[str, float]:
    key = os.environ.get("EIA_API_KEY", "").strip()
    if not key:
        raise RuntimeError("EIA_API_KEY not set")
    out: dict[str, float] = {}
    offset = 0
    while True:
        params = [
            ("api_key", key),
            ("frequency", "hourly"),
            ("data[0]", "value"),
            ("facets[respondent][]", respondent),
            ("facets[type][]", "D"),
            ("start", start.strftime("%Y-%m-%dT%H")),
            ("end", end.strftime("%Y-%m-%dT%H")),
            ("sort[0][column]", "period"),
            ("sort[0][direction]", "asc"),
            ("length", "5000"),
            ("offset", str(offset)),
        ]
        resp = requests.get(EIA_URL, params=params, timeout=TIMEOUT)
        resp.raise_for_status()
        rows = resp.json().get("response", {}).get("data", [])
        if not rows:
            break
        for row in rows:
            val = row.get("value")
            period = row.get("period")
            if val is None or not period:
                continue
            # EIA periods look like "2025-07-01T14"; normalise to an ISO hour.
            stamp = datetime.strptime(period, "%Y-%m-%dT%H").replace(tzinfo=timezone.utc)
            out[stamp.isoformat()] = float(val)
        if len(rows) < 5000:
            break
        offset += 5000
    return out


def _fetch_temps(lat: float, lon: float, start: datetime, end: datetime) -> dict[str, float]:
    params = {
        "latitude": lat, "longitude": lon,
        "start_date": start.date().isoformat(),
        "end_date": end.date().isoformat(),
        "hourly": "temperature_2m",
        "temperature_unit": "fahrenheit",
        "timezone": "UTC",
    }
    resp = requests.get(METEO_URL, params=params, timeout=TIMEOUT)
    resp.raise_for_status()
    hourly = resp.json().get("hourly", {})
    stamps = hourly.get("time", [])
    temps = hourly.get("temperature_2m", [])
    out: dict[str, float] = {}
    for s, v in zip(stamps, temps):
        if v is None:
            continue
        out[datetime.fromisoformat(s).replace(tzinfo=timezone.utc).isoformat()] = float(v)
    return out


def fetch_live() -> list[dict]:
    end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(days=LOOKBACK_DAYS)
    series = []
    for reg in REGIONS:
        ba = reg["ba"]
        demand = _fetch_eia_demand(EIA_RESPONDENT[ba], start, end)
        if len(demand) < 500:
            raise RuntimeError(f"{ba}: only {len(demand)} hourly points from EIA")
        try:
            temps = _fetch_temps(reg["lat"], reg["lon"], start, end)
        except Exception as exc:  # noqa: BLE001 - demand alone is still usable
            log(f"electricity: Open-Meteo failed for {ba} ({exc}); no temp covariate")
            temps = {}

        stamps = sorted(demand)
        y = [demand[s] for s in stamps]
        temp_f = [temps.get(s) for s in stamps]
        if any(v is None for v in temp_f):
            # Forward/back-fill the handful of gaps the archive leaves.
            last = next((v for v in temp_f if v is not None), reg["t_mean"])
            filled = []
            for v in temp_f:
                last = v if v is not None else last
                filled.append(last)
            temp_f = filled

        series.append({
            "source": "electricity",
            "key": ba,
            "unit": "MW",
            "y_label": "Demand (MW)",
            "x_label": "Hour",
            "freq": "hourly",
            "is_seed": False,
            "t": stamps,
            "y": [round(float(v), 1) for v in y],
            "aux": {"temp_f": [round(float(v), 1) for v in temp_f]},
            "meta": {"region": ba, "city": reg["city"],
                     "lat": reg["lat"], "lon": reg["lon"],
                     "source_note": "EIA-930 hourly demand + Open-Meteo archive"},
            "events": [],
        })
        log(f"electricity: {ba} live {len(y)} hours")
    return series


def load(use_live: bool = True) -> list[dict]:
    return load_with_fallback("electricity", fetch_live, use_live=use_live,
                              max_cache_hours=12.0)


if __name__ == "__main__":
    for s in load():
        print(s["key"], len(s["y"]), "seed" if s["is_seed"] else "live")
