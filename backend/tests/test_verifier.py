"""Verifier plumbing without the model: chunking, retrieval, the verdict rule."""

from app.db import SessionLocal, init_db
from app.models import Headline, Passage
from ingest.articles import chunk
from verifier.model import aggregate
from verifier.retrieval import retrieve


def test_chunk_splits_on_sentences_near_the_target_size():
    para = " ".join(f"Sentence number {i} has exactly seven words." for i in range(40))
    out = chunk(para, words=35, limit=5)
    assert len(out) == 5 and all(c.endswith(".") for c in out)
    assert all(30 <= len(c.split()) <= 50 for c in out)


def test_aggregate_rules():
    s = {"supported": 0.9, "refuted": 0.05, "nei": 0.05}
    r = {"supported": 0.1, "refuted": 0.8, "nei": 0.1}
    n = {"supported": 0.2, "refuted": 0.2, "nei": 0.6}
    assert aggregate([s, n])[0] == "supported"
    assert aggregate([n, r])[0] == "refuted"
    assert aggregate([s, r])[0] == "supported"        # strongest wins
    assert aggregate([n, n])[0] == "nei"
    assert aggregate([])[0] == "nei"


def test_retrieval_finds_the_source_and_breaking_mode_hides_it():
    init_db()
    with SessionLocal() as db:
        h = Headline(text="Zorblax council approves glimmerfruit tariff", norm="zorblax-test",
                     snippet="The Zorblax council voted to approve a glimmerfruit tariff.", active=True)
        db.add(h)
        db.flush()
        db.add(Passage(headline_id=h.id, idx=0, kind="snippet", text=h.snippet))
        db.commit()
        hid = h.id
    assert retrieve("Zorblax glimmerfruit tariff", 3)[0].headline_id == hid
    assert all(x.headline_id != hid for x in retrieve("Zorblax glimmerfruit tariff", 3, exclude_headline_id=hid))
