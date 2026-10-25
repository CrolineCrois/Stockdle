"""Check a post: claims are split out, scored against evidence, nothing stored."""

import pytest
from fastapi.testclient import TestClient

from app.db import init_db


@pytest.fixture(scope="module")
def client():
    init_db()
    from ingest.seed import main as seed
    seed()                                   # a corpus for retrieval
    from app.main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def one_passage(monkeypatch):
    from app import claimcheck
    monkeypatch.setattr(claimcheck, "local_evidence", lambda claim: [claimcheck.Passage(
        "135 people were arrested as marches were held across France.", "Test", "", "game")])


def _fake_scorer(claim, passages):
    # Contradict anything mentioning "35"; support everything else.
    return [{"supported": 0.05, "refuted": 0.9, "nei": 0.05} if "35" in claim
            else {"supported": 0.9, "refuted": 0.05, "nei": 0.05} for _ in passages]


def test_check_splits_claims_and_gives_one_verdict_each(client):
    from app import claimcheck
    r = claimcheck.check("Police said 35 people were arrested at the marches today. "
                         "The protests took place across several French cities on Saturday.",
                         fresh=False, scorer=_fake_scorer)
    assert len(r.claims) == 2 and not r.fresh
    verdicts = [c.verdict for c in r.claims]
    assert verdicts[0] == "refuted" and verdicts[1] == "supported"
    assert all(p.kind == "game" for c in r.claims for p in c.passages)


def test_check_endpoint_rejects_bare_links_and_stores_nothing(client, monkeypatch):
    from app import claimcheck
    from app.db import SessionLocal
    from app.models import CheckFeedback
    real = claimcheck.check
    monkeypatch.setattr(claimcheck, "check", lambda text: real(text, fresh=False, scorer=_fake_scorer))
    assert client.post("/api/check", json={"text": "https://x.com/someone/status/123"}).status_code == 422
    body = client.post("/api/check", json={"text": "Police said 35 people were arrested at the marches today."}).json()
    assert body["claims"][0]["verdict"] == "refuted"
    with SessionLocal() as db:
        before = db.query(CheckFeedback).count()
    ok = client.post("/api/check/feedback", json={"text": "x" * 20, "result": body, "feedback": "wrong_true"})
    assert ok.status_code == 200
    with SessionLocal() as db:
        assert db.query(CheckFeedback).count() == before + 1


def test_a_passage_about_another_place_cannot_decide():
    from app.claimcheck import names, on_topic
    n = names("Police arrested over 500 protesters in Paris today.")
    assert n == {"paris"}
    assert not on_topic(n, "Dozens arrested in the Albanian capital Tirana.")
    assert on_topic(n, "Parisian police detained nearly 1,000 people.")
