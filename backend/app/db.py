"""Engine, session factory, and the round catalogue loader."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from . import config
from .models import Base, Round

config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    config.DB_URL,
    future=True,
    connect_args={"check_same_thread": False, "timeout": 20},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False,
                            class_=Session, future=True)


def init_db() -> None:
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        # WAL keeps the background retrain from blocking gameplay writes.
        conn.exec_driver_sql("PRAGMA journal_mode=WAL")
        conn.exec_driver_sql("PRAGMA synchronous=NORMAL")
        _migrate(conn)


def _migrate(conn) -> None:
    """Additive migrations for databases created by an earlier build.

    No Alembic for a hackathon demo, but a schema change must not force people
    to delete their database and lose a populated leaderboard mid-event.
    """
    have = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(rounds)")}
    if have and "active" not in have:
        conn.exec_driver_sql(
            "ALTER TABLE rounds ADD COLUMN active BOOLEAN NOT NULL DEFAULT 1")


def get_session() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def load_rounds_catalogue(path: Path | None = None) -> tuple[int, int]:
    """Sync ``data/rounds/rounds.json`` into the rounds table.

    Returns ``(added, retired)``. Idempotent: re-running after a pipeline
    rebuild adds new rounds and refreshes payloads without touching accumulated
    crowd statistics.

    Rounds that the rebuild dropped are **retired**, not deleted. A rebuild can
    change round ids (they hash the cut position, which moves when the window
    geometry or the upstream data changes), so without this the old rows linger
    and keep getting dealt -- serving stale context text, and in the worst case
    a round whose geometry no longer matches the current canvas. Deleting them
    instead would orphan every drawing and leaderboard score that references
    them, so they are simply never dealt again.
    """
    path = path or (config.ROUNDS_DIR / "rounds.json")
    if not path.exists():
        return 0, 0
    records = json.loads(path.read_text(encoding="utf-8"))
    current = {rec["id"] for rec in records}
    added = retired = 0
    with SessionLocal() as db:
        existing = {r.id: r for r in db.scalars(select(Round)).all()}
        for rec in records:
            row = existing.get(rec["id"])
            if row is None:
                db.add(Round(
                    id=rec["id"], type=rec["type"], source_key=rec["source_key"],
                    is_seed=bool(rec.get("is_seed")),
                    payload_json=json.dumps(rec), crowd_sum_json="", crowd_n=0,
                    active=True,
                ))
                added += 1
            else:
                row.payload_json = json.dumps(rec)
                row.type = rec["type"]
                row.is_seed = bool(rec.get("is_seed"))
                row.active = True
        for rid, row in existing.items():
            if rid not in current and row.active:
                row.active = False
                retired += 1
        db.commit()
    return added, retired
