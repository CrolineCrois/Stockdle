"""Scrape real headlines plus a short article snippet from news RSS feeds.

    python -m ingest.scrape_rss              # feeds from config (SIP_FEEDS)
    python -m ingest.scrape_rss --write-seed # also refresh data/seed/headlines.json

Each item keeps its source URL and publish date. Items are deduplicated on a
normalised form of the headline, across feeds and across runs. Headlines that
make poor game material are skipped: very short or long ones, questions,
live blogs, quizzes, opinion pieces, and anything without a snippet.
"""

from __future__ import annotations

import argparse
import calendar
import html
import json
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

from sqlalchemy import select

from app import config
from app.db import SessionLocal, init_db
from app.models import Headline

AGENT = "SneakItPast/0.1 (hackathon research game)"
SKIP_PREFIXES = ("watch", "live", "video", "quiz", "opinion", "analysis", "in pictures",
                 "podcast", "listen", "photos", "explainer", "review")
# Explainers and features rarely state a checkable fact, so there is nothing to twist.
SKIP_STARTS = ("why ", "how ", "what ", "who ", "when ", "where ", "the week in")
SNIPPET_CHARS = 400
_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")


def normalise(text: str) -> str:
    return _SPACE.sub(" ", re.sub(r"[^a-z0-9 ]", " ", text.lower())).strip()


_READ_MORE = re.compile(r"\s*(continue reading|read more)\s*(\.\.\.|…)?\s*$", re.IGNORECASE)


def clean(text: str) -> str:
    text = _SPACE.sub(" ", html.unescape(_TAG.sub(" ", text or ""))).strip()
    return _READ_MORE.sub("", text).strip()


def trim_snippet(text: str, limit: int = SNIPPET_CHARS) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind(". "), cut.rfind("? "), cut.rfind("! "))
    return cut[:end + 1] if end > limit // 2 else cut.rsplit(" ", 1)[0] + "…"


def usable(title: str, snippet: str) -> bool:
    words = title.split()
    low = title.lower()
    return (6 <= len(words) <= 22 and "?" not in title and len(snippet) >= 40
            and not any(low.startswith(p) for p in SKIP_PREFIXES + SKIP_STARTS)
            and not any(f"{p}:" in low for p in SKIP_PREFIXES))


KNOWN_SOURCES = {"bbci.co.uk": "BBC News", "bbc.co.uk": "BBC News", "npr.org": "NPR",
                 "theguardian.com": "The Guardian", "aljazeera.com": "Al Jazeera",
                 "pbs.org": "PBS NewsHour", "cbsnews.com": "CBS News",
                 "apnews.com": "AP", "reuters.com": "Reuters", "dw.com": "DW",
                 "france24.com": "France 24", "skynews.com": "Sky News",
                 "abcnews.go.com": "ABC News", "nytimes.com": "The New York Times",
                 "latimes.com": "Los Angeles Times", "sciencedaily.com": "ScienceDaily",
                 "thehindu.com": "The Hindu", "rte.ie": "RTÉ", "euronews.com": "Euronews",
                 "independent.co.uk": "The Independent", "japantimes.co.jp": "The Japan Times",
                 "rnz.co.nz": "RNZ", "espn.com": "ESPN", "cnbc.com": "CNBC",
                 "foxnews.com": "Fox News", "abc.net.au": "ABC Australia", "cbc.ca": "CBC News",
                 "channelnewsasia.com": "CNA", "techcrunch.com": "TechCrunch",
                 "theverge.com": "The Verge", "newscientist.com": "New Scientist"}


def source_name(feed_url: str, parsed) -> str:
    host = urlparse(feed_url).netloc.lower()
    for domain, name in KNOWN_SOURCES.items():
        if host == domain or host.endswith("." + domain):
            return name
    title = (parsed.feed.get("title") or "").strip()
    return (title.split(" - ")[0].split(" | ")[0].split(" – ")[0] or host)[:80]


def fetch(feeds: list[str]) -> list[dict]:
    import feedparser  # imported lazily: optional for players, needed to scrape

    items: list[dict] = []
    for url in feeds:
        parsed = feedparser.parse(url, agent=AGENT)
        if not parsed.entries:
            print(f"[scrape] {url}: no entries ({parsed.get('bozo_exception', 'empty')})")
            continue
        src = source_name(url, parsed)
        kept = 0
        for e in parsed.entries:
            title = clean(e.get("title", ""))
            snippet = trim_snippet(clean(e.get("summary", "")))
            if not usable(title, snippet):
                continue
            stamp = e.get("published_parsed") or e.get("updated_parsed")
            published = (datetime.fromtimestamp(calendar.timegm(stamp), tz=timezone.utc)
                         .isoformat() if stamp else None)
            items.append({"text": title, "snippet": snippet, "source": src,
                          "url": e.get("link", ""), "published_at": published})
            kept += 1
        print(f"[scrape] {src}: {kept}/{len(parsed.entries)} usable")
    return items


def store(items: list[dict], *, is_seed: bool = False) -> int:
    """Insert new headlines, skipping any whose normalised text already exists."""
    init_db()
    added = 0
    with SessionLocal() as db:
        seen = set(db.scalars(select(Headline.norm)).all())
        for it in items:
            key = normalise(it["text"])
            if not key or key in seen:
                continue
            seen.add(key)
            pub = it.get("published_at")
            db.add(Headline(
                text=it["text"], norm=key, snippet=it.get("snippet", ""),
                source=it.get("source", ""), url=it.get("url", ""),
                published_at=(datetime.fromisoformat(pub).astimezone(timezone.utc)
                              .replace(tzinfo=None) if pub else None),
                is_seed=is_seed,
            ))
            added += 1
        db.commit()
    return added


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--write-seed", action="store_true",
                    help="also write the scraped items to data/seed/headlines.json")
    args = ap.parse_args()
    items = fetch(config.FEEDS)
    added = store(items)
    print(f"[scrape] {len(items)} usable, {added} new")
    if args.write_seed:
        unique = list({normalise(i["text"]): i for i in items}.values())
        config.SEED_FILE.parent.mkdir(parents=True, exist_ok=True)
        config.SEED_FILE.write_text(json.dumps(unique, indent=1, ensure_ascii=False),
                                    encoding="utf-8")
        print(f"[scrape] wrote {len(unique)} items to {config.SEED_FILE}")


if __name__ == "__main__":
    main()
