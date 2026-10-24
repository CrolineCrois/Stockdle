"""Live Google Trends interest-over-time via pytrends.

pytrends is rate-limited hard and frequently returns 429, so this module:

* requests terms in small batches with a pause between them,
* keeps whatever it managed to fetch rather than failing the whole run,
* caches for 48h (``max_cache_hours``), and
* falls back to ``data/seed/trends.json`` on any trouble.
"""

from __future__ import annotations

import time

from .common import load_with_fallback, log
from .seed_gen import TREND_TERMS

TIMEFRAME = "today 5-y"     # weekly resolution
GEO = "US"
# One term per request, deliberately. Google Trends normalises interest
# *within a payload*: ask for ["world cup", "tax extension", "air fryer
# recipes"] together and the World Cup takes the 100 while the other two are
# crushed to a flat 0-1 line, which makes an unplayable round. Alone, every term
# is scaled to its own peak.
BATCH = 1
PAUSE_S = 2.5


def _fetch_batch(pt, chunk: list[str], attempts: int = 3):
    """Request one batch, retrying ourselves with exponential backoff.

    pytrends' own ``retries``/``backoff_factor`` arguments build a urllib3
    ``Retry`` with ``method_whitelist``, which urllib3 2.x removed -- passing
    them makes every request raise ``TypeError``. So the constructor is left
    bare and the backoff lives here instead.
    """
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            pt.build_payload(chunk, cat=0, timeframe=TIMEFRAME, geo=GEO, gprop="")
            return pt.interest_over_time()
        except Exception as exc:  # noqa: BLE001
            last = exc
            if attempt < attempts - 1:
                time.sleep(PAUSE_S * (2 ** attempt))
    raise last if last else RuntimeError("unreachable")


def fetch_live() -> list[dict]:
    from pytrends.request import TrendReq  # imported lazily

    pt = TrendReq(hl="en-US", tz=0, timeout=(10, 25))
    log(f'trends: fetching {len(TREND_TERMS)} terms one at a time '
        f'(per-term normalisation)')
    terms = [spec["term"] for spec in TREND_TERMS]
    series: list[dict] = []

    for i in range(0, len(terms), BATCH):
        chunk = terms[i:i + BATCH]
        try:
            frame = _fetch_batch(pt, chunk)
        except Exception as exc:  # noqa: BLE001 - keep whatever already worked
            log(f"trends: batch {chunk} failed ({type(exc).__name__}); skipping")
            time.sleep(PAUSE_S)
            continue
        if frame is None or frame.empty:
            log(f"trends: batch {chunk} empty")
            time.sleep(PAUSE_S)
            continue
        if "isPartial" in frame.columns:
            frame = frame[~frame["isPartial"].astype(bool)]
        for term in chunk:
            if term not in frame.columns or len(frame[term]) < 120:
                continue
            series.append({
                "source": "trends",
                "key": term,
                "unit": "",
                "y_label": "Search interest",
                "x_label": "Weeks",
                "freq": "weekly",
                "is_seed": False,
                "t": [ts.date().isoformat() for ts in frame.index],
                "y": [float(v) for v in frame[term].tolist()],
                "aux": {},
                "meta": {"term": term, "geo": GEO,
                         "source_note": f"pytrends interest_over_time {TIMEFRAME}"},
                "events": [],
            })
            log(f"trends: {term} live {len(frame[term])} weeks")
        time.sleep(PAUSE_S)

    if len(series) < 4:
        raise RuntimeError(f"only {len(series)} terms survived pytrends rate limits")
    return series


def load(use_live: bool = True) -> list[dict]:
    return load_with_fallback("trends", fetch_live, use_live=use_live,
                              max_cache_hours=48.0)


if __name__ == "__main__":
    for s in load():
        print(s["key"], len(s["y"]), "seed" if s["is_seed"] else "live")
