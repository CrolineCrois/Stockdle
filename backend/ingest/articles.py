"""Fetch article bodies and split them into evidence passages for the verifier.

    python -m ingest.articles            # headlines with no passages yet
    python -m ingest.articles --refetch  # everything again

RSS snippets are one or two sentences, too thin to verify most claims against,
so each article's page is fetched and its main text extracted (trafilatura).
Every headline gets its snippet as passage 0; the body is split into chunks of
a few sentences (~70 words) after that. Pages that block us or yield almost no
text fall back to the snippet alone, and that is recorded, not hidden.

Polite by construction: an identifying user agent, a pause between requests,
and each article fetched once.
"""

from __future__ import annotations

import argparse
import re
import time

import httpx
from sqlalchemy import delete, select

from app.db import SessionLocal, init_db
from app.models import Headline, Passage

AGENT = "Mozilla/5.0 (compatible; SneakItPast/0.1; hackathon research game)"
PAUSE_S = 1.0
CHUNK_WORDS = 70
MAX_CHUNKS = 10
MIN_BODY_CHARS = 500
_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'“‘])")


def chunk(text: str, words: int = CHUNK_WORDS, limit: int = MAX_CHUNKS) -> list[str]:
    """Sentence-aware chunks of roughly ``words`` words."""
    out, cur, n = [], [], 0
    for para in [p.strip() for p in text.split("\n") if len(p.split()) >= 6]:
        for sent in _SENT.split(para):
            cur.append(sent)
            n += len(sent.split())
            if n >= words:
                out.append(" ".join(cur))
                cur, n = [], 0
                if len(out) >= limit:
                    return out
    if cur and n >= 15:
        out.append(" ".join(cur))
    return out[:limit]


def fetch_body(client: httpx.Client, url: str) -> str:
    import trafilatura

    r = client.get(url)
    if r.status_code != 200:
        return ""
    return trafilatura.extract(r.text, include_comments=False, include_tables=False) or ""


def run(*, refetch: bool = False) -> dict:
    init_db()
    stats = {"headlines": 0, "with_body": 0, "snippet_only": 0, "passages": 0, "errors": 0}
    with SessionLocal() as db, httpx.Client(timeout=15, follow_redirects=True,
                                             headers={"User-Agent": AGENT}) as client:
        done = set(db.scalars(select(Passage.headline_id)).all())
        heads = [h for h in db.scalars(select(Headline).where(Headline.active)).all()
                 if refetch or h.id not in done]
        for h in heads:
            stats["headlines"] += 1
            body = ""
            if h.url:
                try:
                    body = fetch_body(client, h.url)
                except httpx.HTTPError:
                    stats["errors"] += 1
                time.sleep(PAUSE_S)
            chunks = chunk(body) if len(body) >= MIN_BODY_CHARS else []
            db.execute(delete(Passage).where(Passage.headline_id == h.id))
            db.add(Passage(headline_id=h.id, idx=0, kind="snippet", text=h.snippet or h.text))
            for i, text in enumerate(chunks, start=1):
                db.add(Passage(headline_id=h.id, idx=i, kind="body", text=text))
            stats["with_body" if chunks else "snippet_only"] += 1
            stats["passages"] += 1 + len(chunks)
            db.commit()
    return stats


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refetch", action="store_true")
    print(f"[articles] {run(refetch=ap.parse_args().refetch)}")


if __name__ == "__main__":
    main()
