"""Load the committed sample headlines so the game works before any scraping.

    python -m ingest.seed

``data/seed/headlines.json`` holds real headlines captured from the configured
RSS feeds, each with its source URL and publish date. Re-running is safe:
existing headlines are skipped.
"""

from __future__ import annotations

import json

from app import config

from .scrape_rss import store


def main() -> int:
    if not config.SEED_FILE.exists():
        raise SystemExit(f"no seed file at {config.SEED_FILE}; "
                         "run `python -m ingest.scrape_rss --write-seed` once")
    items = json.loads(config.SEED_FILE.read_text(encoding="utf-8"))
    added = store(items, is_seed=True)
    print(f"[seed] {added} new headlines ({len(items)} in the seed file)")
    return added


if __name__ == "__main__":
    main()
