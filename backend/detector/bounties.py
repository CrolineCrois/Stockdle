"""Flag bounty headlines: the ones the current detector already suspects most.

A true headline the detector scores as fairly suspicious *before any edit* is
a hard target -- almost any lie added to it will push suspicion over the line.
Sneaking one past is worth 3x and buys +5 seconds on the clock.

    python -m detector.bounties
"""

from __future__ import annotations

from sqlalchemy import select

from app import config
from app.db import SessionLocal, init_db
from app.models import Headline

from . import registry


def refresh(fraction: float | None = None) -> int:
    fraction = config.BOUNTY_FRACTION if fraction is None else fraction
    det = registry.current()
    with SessionLocal() as db:
        rows = db.scalars(select(Headline).where(Headline.active)).all()
        if not rows:
            return 0
        scores = det.predict([(h.text, h.snippet) for h in rows])
        for h, p in zip(rows, scores):
            h.detector_p = round(p, 4)
        n = max(1, int(round(len(rows) * fraction)))
        ranked = sorted(zip(scores, rows), key=lambda x: -x[0])
        bounty_ids = {h.id for _, h in ranked[:n]}
        for h in rows:
            h.is_bounty = h.id in bounty_ids
        db.commit()
        return n


if __name__ == "__main__":
    init_db()
    print(f"[bounties] flagged {refresh()} bounty headlines with detector {registry.current_name()}")
