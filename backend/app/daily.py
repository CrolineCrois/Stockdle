"""Daily 5: the same five rounds for everyone, derived from the date alone.

No stored schedule -- the date seeds a PRNG, so any server (or a replay next
week) reproduces the same puzzle. The mix is deliberately one round of each
type plus a wildcard, so the daily always shows off all four sources.
"""

from __future__ import annotations

import hashlib
import random
from datetime import date, timedelta

# Day 1 was 2026-10-11, which makes 2026-10-24 "TAPE #14".
EPOCH = date(2026, 10, 10)
TYPE_ORDER = ("electricity", "stock", "trends", "fake_stock")


def daily_number(day: date | None = None) -> int:
    day = day or date.today()
    return max(1, (day - EPOCH).days)


def _seed(day: date) -> int:
    digest = hashlib.sha256(f"tape-daily-{day.isoformat()}".encode()).hexdigest()
    return int(digest[:16], 16)


def pick_daily(ids_by_type: dict[str, list[str]], day: date | None = None,
               n: int = 5) -> list[str]:
    """Deterministically choose the day's rounds from the catalogue."""
    day = day or date.today()
    rng = random.Random(_seed(day))
    pool = {k: sorted(v) for k, v in ids_by_type.items() if v}
    if not pool:
        return []

    chosen: list[str] = []
    for kind in TYPE_ORDER:
        if kind in pool and len(chosen) < n:
            chosen.append(rng.choice(pool[kind]))

    # Fill any remainder (including when a type is missing) from everything left.
    leftovers = sorted({i for ids in pool.values() for i in ids} - set(chosen))
    while len(chosen) < n and leftovers:
        pick = rng.choice(leftovers)
        leftovers.remove(pick)
        chosen.append(pick)

    rng.shuffle(chosen)
    return chosen[:n]


def share_grid(scores: list[int], beat_ai: int, number: int | None = None) -> str:
    """The copyable result line.

    Scores only -- never a headline, never a ticker. Fabricated headlines in
    particular must not travel outside a round that labels them as fake.
    """
    number = number or daily_number()
    marks = " · ".join(str(int(s)) for s in scores)
    best = max(scores) if scores else 0
    icon = "🎯" if best >= 95 else ("🔥" if best >= 75 else "📈")
    return f"TAPE #{number} {icon} {marks} | beat AI {beat_ai}/{len(scores)}"


def yesterday(day: date | None = None) -> date:
    return (day or date.today()) - timedelta(days=1)
