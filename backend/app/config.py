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
# Points multiplier per level below the newest fact-checker (older = easier).
LEVEL_STEP_MULT = _env("SIP_LEVEL_STEP_MULT", 0.5)
# Tries per headline; 0 = unlimited while the clock runs (the default).
MAX_ATTEMPTS = _env("SIP_MAX_ATTEMPTS", 0)
# Unlimited tries still cost a judge call each: at least this long between submits.
MIN_SUBMIT_GAP_S = _env("SIP_MIN_SUBMIT_GAP_S", 1.0)
MAX_WORD_CHANGES = _env("SIP_MAX_WORD_CHANGES", 3)
SNEAK_THRESHOLD = _env("SIP_SNEAK_THRESHOLD", 0.5)  # suspicion below this sneaks past
NEAR_MISS_FROM = _env("SIP_NEAR_MISS_FROM", 0.4)    # "so close!" band: [0.4, 0.5)

# Timer: base seconds, minus one per streak level, floored; bounties get extra.
TIMER_BASE_S = _env("SIP_TIMER_BASE_S", 40.0)
TIMER_MIN_S = _env("SIP_TIMER_MIN_S", 20.0)
TIMER_STREAK_STEP_S = _env("SIP_TIMER_STREAK_STEP_S", 2.0)
TIMER_BOUNTY_BONUS_S = _env("SIP_TIMER_BOUNTY_BONUS_S", 10.0)
# Network slack: a submit that lands this many seconds after zero still counts.
TIMER_GRACE_S = _env("SIP_TIMER_GRACE_S", 1.5)

# Novelty ("zero-day exploit"): min cosine distance to every earlier exploit.
NOVELTY_THRESHOLD = _env("SIP_NOVELTY_THRESHOLD", 0.35)
# Share of the headline pool flagged as bounties.
BOUNTY_FRACTION = _env("SIP_BOUNTY_FRACTION", 0.15)

# --- data ------------------------------------------------------------------
DEFAULT_FEEDS = ",".join([
    # world
    "https://feeds.bbci.co.uk/news/world/rss.xml",
    "https://feeds.npr.org/1001/rss.xml",
    "https://www.theguardian.com/world/rss",
    "https://www.aljazeera.com/xml/rss/all.xml",
    "https://www.pbs.org/newshour/feeds/rss/headlines",
    "https://rss.dw.com/rdf/rss-en-all",
    "https://www.france24.com/en/rss",
    "https://feeds.skynews.com/feeds/rss/world.xml",
    "https://abcnews.go.com/abcnews/internationalheadlines",
    "https://www.cbsnews.com/latest/rss/world",
    "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
    # UK / US
    "https://feeds.bbci.co.uk/news/uk/rss.xml",
    "https://feeds.bbci.co.uk/news/world/us_and_canada/rss.xml",
    "https://www.theguardian.com/uk-news/rss",
    "https://www.theguardian.com/us-news/rss",
    "https://feeds.npr.org/1014/rss.xml",
    # business, science, tech, sport
    "https://feeds.bbci.co.uk/news/business/rss.xml",
    "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml",
    "https://feeds.bbci.co.uk/news/technology/rss.xml",
    "https://www.theguardian.com/business/rss",
    "https://www.theguardian.com/science/rss",
    "https://www.theguardian.com/technology/rss",
    "https://www.theguardian.com/sport/rss",
    "https://feeds.npr.org/1006/rss.xml",
    "https://feeds.npr.org/1007/rss.xml",
    # more sections and outlets (tested: >= 5 usable headlines each)
    "https://abcnews.go.com/abcnews/healthheadlines",
    "https://abcnews.go.com/abcnews/moneyheadlines",
    "https://abcnews.go.com/abcnews/politicsheadlines",
    "https://abcnews.go.com/abcnews/technologyheadlines",
    "https://abcnews.go.com/abcnews/topstories",
    "https://abcnews.go.com/abcnews/usheadlines",
    "https://feeds.bbci.co.uk/news/education/rss.xml",
    "https://feeds.bbci.co.uk/news/entertainment_and_arts/rss.xml",
    "https://feeds.bbci.co.uk/news/health/rss.xml",
    "https://feeds.bbci.co.uk/news/politics/rss.xml",
    "https://feeds.bbci.co.uk/news/world/africa/rss.xml",
    "https://feeds.bbci.co.uk/news/world/asia/rss.xml",
    "https://feeds.bbci.co.uk/news/world/europe/rss.xml",
    "https://feeds.bbci.co.uk/news/world/latin_america/rss.xml",
    "https://feeds.bbci.co.uk/news/world/middle_east/rss.xml",
    "https://feeds.bbci.co.uk/sport/rss.xml",
    "https://feeds.npr.org/1003/rss.xml",
    "https://feeds.npr.org/1004/rss.xml",
    "https://feeds.npr.org/1019/rss.xml",
    "https://feeds.npr.org/1025/rss.xml",
    "https://moxie.foxnews.com/google-publisher/politics.xml",
    "https://moxie.foxnews.com/google-publisher/us.xml",
    "https://moxie.foxnews.com/google-publisher/world.xml",
    "https://techcrunch.com/feed/",
    "https://www.abc.net.au/news/feed/45910/rss.xml",
    "https://www.abc.net.au/news/feed/51120/rss.xml",
    "https://www.cbc.ca/webfeed/rss/rss-business",
    "https://www.cbc.ca/webfeed/rss/rss-canada",
    "https://www.cbc.ca/webfeed/rss/rss-health",
    "https://www.cbc.ca/webfeed/rss/rss-technology",
    "https://www.cbc.ca/webfeed/rss/rss-world",
    "https://www.cbsnews.com/latest/rss/health",
    "https://www.cbsnews.com/latest/rss/moneywatch",
    "https://www.cbsnews.com/latest/rss/politics",
    "https://www.cbsnews.com/latest/rss/science",
    "https://www.cbsnews.com/latest/rss/technology",
    "https://www.cbsnews.com/latest/rss/us",
    "https://www.channelnewsasia.com/api/v1/rss-outbound-feed?_format=xml",
    "https://www.channelnewsasia.com/api/v1/rss-outbound-feed?_format=xml&category=6511",
    "https://www.cnbc.com/id/100003114/device/rss/rss.html",
    "https://www.cnbc.com/id/100727362/device/rss/rss.html",
    "https://www.espn.com/espn/rss/news",
    "https://www.euronews.com/rss",
    "https://www.france24.com/en/africa/rss",
    "https://www.france24.com/en/americas/rss",
    "https://www.france24.com/en/asia-pacific/rss",
    "https://www.france24.com/en/business-tech/rss",
    "https://www.france24.com/en/europe/rss",
    "https://www.france24.com/en/middle-east/rss",
    "https://www.independent.co.uk/news/uk/rss",
    "https://www.independent.co.uk/news/world/rss",
    "https://www.japantimes.co.jp/feed/",
    "https://www.latimes.com/california/rss2.0.xml",
    "https://www.latimes.com/world-nation/rss2.0.xml",
    "https://www.newscientist.com/feed/home/",
    "https://www.pbs.org/newshour/feeds/rss/economy",
    "https://www.pbs.org/newshour/feeds/rss/health",
    "https://www.pbs.org/newshour/feeds/rss/nation",
    "https://www.pbs.org/newshour/feeds/rss/politics",
    "https://www.pbs.org/newshour/feeds/rss/science",
    "https://www.pbs.org/newshour/feeds/rss/world",
    "https://www.rnz.co.nz/rss/national.xml",
    "https://www.rte.ie/feeds/rss/?index=/news/",
    "https://www.rte.ie/feeds/rss/?index=/news/world/",
    "https://www.sciencedaily.com/rss/top/science.xml",
    "https://www.theguardian.com/australia-news/rss",
    "https://www.theguardian.com/culture/rss",
    "https://www.theguardian.com/education/rss",
    "https://www.theguardian.com/environment/rss",
    "https://www.theguardian.com/football/rss",
    "https://www.theguardian.com/global-development/rss",
    "https://www.theguardian.com/media/rss",
    "https://www.theguardian.com/money/rss",
    "https://www.theguardian.com/politics/rss",
    "https://www.theguardian.com/society/rss",
    "https://www.theguardian.com/world/africa/rss",
    "https://www.theguardian.com/world/americas/rss",
    "https://www.theguardian.com/world/asia/rss",
    "https://www.theguardian.com/world/europe-news/rss",
    "https://www.theguardian.com/world/middleeast/rss",
    "https://www.thehindu.com/news/international/feeder/default.rss",
    "https://www.thehindu.com/news/national/feeder/default.rss",
    "https://www.theverge.com/rss/index.xml",
])
FEEDS = [f.strip() for f in _env("SIP_FEEDS", DEFAULT_FEEDS).split(",") if f.strip()]

# --- server ----------------------------------------------------------------
CORS_ORIGINS = [o for o in _env(
    "SIP_CORS_ORIGINS",
    "http://localhost:3000,http://127.0.0.1:3000,http://localhost:3001",
).split(",") if o]
# Deployed frontends, e.g. "https://.*\.vercel\.app" (regex, on top of the list above).
CORS_ORIGIN_REGEX = _env("SIP_CORS_ORIGIN_REGEX", r"https://.*\.vercel\.app")
ADMIN_TOKEN = _env("SIP_ADMIN_TOKEN", "sneak-demo")
SUSPICION_RATE_PER_S = _env("SIP_SUSPICION_RATE_PER_S", 8.0)   # live-meter calls
# Public hosting: every submit is two paid judge calls. Per-IP and global caps.
SUBMITS_PER_IP_PER_MIN = _env("SIP_SUBMITS_PER_IP_PER_MIN", 20)
PLAYERS_PER_IP_PER_HOUR = _env("SIP_PLAYERS_PER_IP_PER_HOUR", 10)
SUBMITS_PER_HOUR = _env("SIP_SUBMITS_PER_HOUR", 2000)          # all players together

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

# --- evidence verifier (decides rounds; see verifier/) -----------------------
VERIFIER_BASE_MODEL = _env("SIP_VERIFIER_BASE", "MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli")
VERIFIER_TOP_K = _env("SIP_VERIFIER_TOP_K", 3)
# A passage refutes / supports the claim when its probability clears this.
VERIFIER_DECIDE_AT = _env("SIP_VERIFIER_DECIDE_AT", 0.5)
VERIFIER_MAX_LEN = _env("SIP_VERIFIER_MAX_LEN", 256)

# What drives the live meter: "glance" = the evidence verifier on the single best
# source passage (tracks the real verdict, ~0.1 s); "style" = the small style model.
METER = _env("SIP_METER", "glance")
