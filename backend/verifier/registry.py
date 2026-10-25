"""Verifier versions: which is live, loading and caching them.

v0 is registered automatically on first use as the off-the-shelf base model.
The live version is re-read every few seconds so a patch day (another
process) takes effect without restarting the API.
"""

from __future__ import annotations

import json
import threading
import time

from sqlalchemy import select, update

from app import config
from app.db import SessionLocal
from app.models import VerifierVersion

from .model import VerifierModel

_cache: dict[str, VerifierModel] = {}
_current: str | None = None
_checked = 0.0
_lock = threading.Lock()
RECHECK_S = 5.0


def ensure_v0() -> None:
    with SessionLocal() as db:
        if db.scalar(select(VerifierVersion.id).limit(1)) is None:
            db.add(VerifierVersion(name="v0", path=config.VERIFIER_BASE_MODEL, is_current=True,
                                   note="off-the-shelf NLI fact verifier, no fine-tuning"))
            db.commit()


def current_name() -> str:
    global _current, _checked
    if _current is None or time.monotonic() - _checked > RECHECK_S:
        ensure_v0()
        with SessionLocal() as db:
            _current = db.scalar(select(VerifierVersion.name).where(VerifierVersion.is_current))
        _checked = time.monotonic()
    return _current


def load(name: str) -> VerifierModel:
    with _lock:
        if name not in _cache:
            with SessionLocal() as db:
                row = db.scalar(select(VerifierVersion).where(VerifierVersion.name == name))
            if row is None:
                raise LookupError(f"no verifier version {name!r}")
            _cache[name] = VerifierModel(name, row.path)
        return _cache[name]


def current() -> VerifierModel:
    return load(current_name())


def evict(name: str) -> None:
    with _lock:
        _cache.pop(name, None)


def register(name: str, path: str, *, train_data: str, n_train: int, metrics: dict,
             note: str, make_current: bool) -> None:
    global _current
    with SessionLocal() as db:
        row = db.scalar(select(VerifierVersion).where(VerifierVersion.name == name))
        if row is not None and row.is_current and not make_current:
            raise ValueError(f"{name} is the live fact-checker; refusing to overwrite it")
        if row is None:
            row = VerifierVersion(name=name, path=path)
            db.add(row)
        row.path, row.train_data, row.n_train = path, train_data, n_train
        row.metrics_json, row.note = json.dumps(metrics), note[:300]
        if make_current:
            db.execute(update(VerifierVersion).values(is_current=False))
            row.is_current = True
        db.commit()
    evict(name)
    if make_current:
        _current = name


def set_current(name: str) -> None:
    global _current
    with SessionLocal() as db:
        db.execute(update(VerifierVersion).values(is_current=False))
        db.execute(update(VerifierVersion).where(VerifierVersion.name == name).values(is_current=True))
        db.commit()
    _current = name


def versions() -> list[VerifierVersion]:
    ensure_v0()
    with SessionLocal() as db:
        return list(db.scalars(select(VerifierVersion).order_by(VerifierVersion.created_at)).all())
