"""Engine and session factory."""

from __future__ import annotations

from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from . import config
from .models import Base

if config.DB_URL.startswith("sqlite"):
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    config.DB_URL,
    future=True,
    connect_args={"check_same_thread": False, "timeout": 20}
    if config.DB_URL.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False,
                            class_=Session, future=True)


def init_db() -> None:
    Base.metadata.create_all(engine)
    if config.DB_URL.startswith("sqlite"):
        with engine.begin() as conn:
            # WAL lets the live meter read while a submission is writing.
            conn.exec_driver_sql("PRAGMA journal_mode=WAL")
            conn.exec_driver_sql("PRAGMA synchronous=NORMAL")


def get_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session
