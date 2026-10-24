"""Configuration. Everything has a working default with no .env and no keys."""

from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    for _candidate in (Path(__file__).resolve().parents[2] / ".env",
                       Path(__file__).resolve().parents[1] / ".env"):
        if _candidate.exists():
            load_dotenv(_candidate)
            break
except Exception:  # noqa: BLE001
    pass

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
DATA_DIR = Path(os.environ.get("TAPE_DATA_DIR", REPO_ROOT / "data"))
ROUNDS_DIR = DATA_DIR / "rounds"

DB_PATH = Path(os.environ.get("TAPE_DB", DATA_DIR / "tape.db"))
DB_URL = f"sqlite+pysqlite:///{DB_PATH.as_posix()}"

# Gameplay
DAILY_ROUNDS = int(os.environ.get("TAPE_DAILY_ROUNDS", 5))
ROUND_SECONDS = int(os.environ.get("TAPE_ROUND_SECONDS", 10))
CURVE_LEN = 50
MIN_CROWD = 3                       # drawings before the crowd curve is used

# AI retraining
RETRAIN_EVERY = int(os.environ.get("TAPE_RETRAIN_EVERY", 25))
BLEND_MIN_ROUNDS = 8                # rounds with a crowd before weights are fit

# Rate limiting
SUBMIT_WINDOW_S = 10.0
SUBMIT_MAX_PER_WINDOW = 12          # per player, across all rounds

CORS_ORIGINS = [o for o in os.environ.get(
    "TAPE_CORS_ORIGINS",
    "http://localhost:3000,http://127.0.0.1:3000,http://localhost:3001",
).split(",") if o]

ADMIN_TOKEN = os.environ.get("TAPE_ADMIN_TOKEN", "tape-demo")
