"""Which detector version is current, and loading versions from disk.

Versions are rows in ``detector_versions``; each points at a directory under
``data/detectors/``. Loaded models are cached, so the live meter never touches
disk after the first call.
"""

from __future__ import annotations

import threading
from pathlib import Path

from sqlalchemy import select, update

from app.db import SessionLocal
from app.models import DetectorVersion

from .base import Detector

_cache: dict[str, Detector] = {}
_current: str | None = None
_lock = threading.Lock()


def _load_row(row: DetectorVersion) -> Detector:
    if row.kind == "baseline":
        from .baseline import BaselineDetector
        return BaselineDetector.load(row.name, Path(row.path))
    if row.kind == "distilbert":
        from .distil import DistilDetector  # phase 2; needs requirements-optional.txt
        return DistilDetector.load(row.name, Path(row.path))
    raise ValueError(f"unknown detector kind {row.kind!r}")


def load(name: str) -> Detector:
    with _lock:
        if name not in _cache:
            with SessionLocal() as db:
                row = db.scalar(select(DetectorVersion).where(DetectorVersion.name == name))
                if row is None:
                    raise LookupError(f"no detector version {name!r}")
                _cache[name] = _load_row(row)
        return _cache[name]


def current_name() -> str:
    global _current
    if _current is None:
        with SessionLocal() as db:
            _current = db.scalar(select(DetectorVersion.name)
                                 .where(DetectorVersion.is_current))
        if _current is None:
            raise LookupError("no current detector; run `python -m detector.train_stub`")
    return _current


def current() -> Detector:
    return load(current_name())


def set_current(name: str) -> None:
    """Make ``name`` the live detector (used by training and patch days)."""
    global _current
    with SessionLocal() as db:
        db.execute(update(DetectorVersion).values(is_current=False))
        db.execute(update(DetectorVersion).where(DetectorVersion.name == name)
                   .values(is_current=True))
        db.commit()
    with _lock:
        _current = name


def forget() -> None:
    """Drop cached state (tests, or after a version is retrained in place)."""
    global _current
    with _lock:
        _cache.clear()
        _current = None
