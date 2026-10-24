"""Configuration. Everything has a working default with no .env and no API key.

Copy ``.env.example`` to ``.env`` (repo root or ``backend/``) to override.
"""

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


def _env(name: str, default):
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return type(default)(raw) if not isinstance(default, bool) else raw.lower() in ("1", "true", "yes")


BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
DATA_DIR = Path(_env("SIP_DATA_DIR", str(REPO_ROOT / "data")))
SEED_FILE = DATA_DIR / "seed" / "headlines.json"
DETECTOR_DIR = DATA_DIR / "detectors"

DB_PATH = Path(_env("SIP_DB", str(DATA_DIR / "sneak.db")))
DB_URL = _env("SIP_DB_URL", f"sqlite+pysqlite:///{DB_PATH.as_posix()}")

# --- the judge -------------------------------------------------------------
# "claude" needs ANTHROPIC_API_KEY; "mock" is a rule-based stand-in for
# development; "auto" uses Claude when a key is set and the mock otherwise.
JUDGE = _env("SIP_JUDGE", "auto")
JUDGE_MODEL = _env("SIP_JUDGE_MODEL", "claude-sonnet-5-5")
JUDGE_TIMEOUT_S = _env("SIP_JUDGE_TIMEOUT_S", 30.0)

# --- the game --------------------------------------------------------------
LIVES = _env("SIP_LIVES", 3)
MAX_ATTEMPTS = _env("SIP_MAX_ATTEMPTS", 3)          # per headline
MAX_WORD_CHANGES = _env("SIP_MAX_WORD_CHANGES", 3)
SNEAK_THRESHOLD = _env("SIP_SNEAK_THRESHOLD", 0.5)  # suspicion below this sneaks past
NEAR_MISS_FROM = _env("SIP_NEAR_MISS_FROM", 0.4)    # "so close!" band: [0.4, 0.5)

# Timer: base seconds, minus one per streak level, floored; bounties get extra.
TIMER_BASE_S = _env("SIP_TIMER_BASE_S", 20.0)
TIMER_MIN_S = _env("SIP_TIMER_MIN_S", 10.0)
TIMER_STREAK_STEP_S = _env("SIP_TIMER_STREAK_STEP_S", 1.0)
TIMER_BOUNTY_BONUS_S = _env("SIP_TIMER_BOUNTY_BONUS_S", 5.0)
# Network slack: a submit that lands this many seconds after zero still counts.
TIMER_GRACE_S = _env("SIP_TIMER_GRACE_S", 1.5)

# Novelty ("zero-day exploit"): min cosine distance to every earlier exploit.
NOVELTY_THRESHOLD = _env("SIP_NOVELTY_THRESHOLD", 0.35)
# Share of the headline pool flagged as bounties.
BOUNTY_FRACTION = _env("SIP_BOUNTY_FRACTION", 0.15)

# --- data ------------------------------------------------------------------
DEFAULT_FEEDS = ",".join([
    "https://feeds.bbci.co.uk/news/world/rss.xml",
    "https://feeds.npr.org/1001/rss.xml",
    "https://www.theguardian.com/world/rss",
    "https://www.aljazeera.com/xml/rss/all.xml",
    "https://www.pbs.org/newshour/feeds/rss/headlines",
])
FEEDS = [f.strip() for f in _env("SIP_FEEDS", DEFAULT_FEEDS).split(",") if f.strip()]

# --- server ----------------------------------------------------------------
CORS_ORIGINS = [o for o in _env(
    "SIP_CORS_ORIGINS",
    "http://localhost:3000,http://127.0.0.1:3000,http://localhost:3001",
).split(",") if o]
ADMIN_TOKEN = _env("SIP_ADMIN_TOKEN", "sneak-demo")
SUSPICION_RATE_PER_S = _env("SIP_SUSPICION_RATE_PER_S", 8.0)   # live-meter calls

# --- detector training (phase 2+) -------------------------------------------
# The LLM that writes v0's training fakes. Only used when an API key is set.
FAKES_MODEL = _env("SIP_FAKES_MODEL", "claude-opus-5-5")
# A small NLI cross-encoder (premise = snippet, claim = headline); any 2-label
# classifier such as distilbert-base-uncased also works. See detector/transformer.py.
DETECTOR_BASE_MODEL = _env("SIP_DETECTOR_BASE", "cross-encoder/nli-deberta-v3-xsmall")
DETECTOR_MAX_LEN = _env("SIP_DETECTOR_MAX_LEN", 160)

# --- OpenAI as an alternative provider ---------------------------------------
# Used for the judge and for v0's training fakes when OPENAI_API_KEY is set and
# no Anthropic key is (or when SIP_JUDGE=openai / SIP_FAKES_PROVIDER=openai).
# Run `python -m judge.check` to see which models your key can use.
OPENAI_JUDGE_MODEL = _env("SIP_OPENAI_JUDGE_MODEL", "gpt-4.1-mini")
OPENAI_FAKES_MODEL = _env("SIP_OPENAI_FAKES_MODEL", "gpt-4.1")
FAKES_PROVIDER = _env("SIP_FAKES_PROVIDER", "auto")   # auto | claude | openai | rules
