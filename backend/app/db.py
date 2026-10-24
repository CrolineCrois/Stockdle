"""Engine and session factory."""

from __future__ import annotations

from typing import Iterator

from sqlalchemy import create_engine, inspect, text
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


def _add_missing_columns() -> None:
    """Additive migrations: add any model column an older database lacks.

    No Alembic for a hackathon, but a schema change must not force anyone to
    delete their database (and its logged attempts) mid-event. Only adds
    columns, with the model's scalar default; never drops or alters.
    """
    insp = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in have:
                    continue
                ddl_type = col.type.compile(dialect=engine.dialect)
                default = col.default.arg if col.default is not None and col.default.is_scalar else None
                clause = ""
                if default is not None:
                    literal = repr(default) if isinstance(default, str) else int(default) \
                        if isinstance(default, bool) else default
                    clause = f" DEFAULT {literal}"
                conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN "{col.name}" {ddl_type}{clause}'))


def init_db() -> None:
    Base.metadata.create_all(engine)
    _add_missing_columns()
    if config.DB_URL.startswith("sqlite"):
        with engine.begin() as conn:
            # WAL lets the live meter read while a submission is writing.
            conn.exec_driver_sql("PRAGMA journal_mode=WAL")
            conn.exec_driver_sql("PRAGMA synchronous=NORMAL")


def get_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session
