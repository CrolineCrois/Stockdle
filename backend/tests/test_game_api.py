"""End-to-end game loop over HTTP, with the mock judge and the stub detector."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal, init_db
from app.models import Attempt, Headline, Round
from detector import registry


@pytest.fixture(scope="module")
def client():
    init_db()
    from detector.train_stub import main as train
    from ingest.seed import main as seed
    import sys
    seed()
    argv, sys.argv = sys.argv, ["train_stub", "--make-current"]
    try:
        train()
    finally:
        sys.argv = argv
    from app.main import app
    with TestClient(app) as c:
        yield c


def new_run(client, name="Tester"):
    pid = client.post("/api/player", json={"name": name}).json()["player_id"]
    state = client.post("/api/run", json={"player_id": pid}).json()
    return pid, state


def headline_of(state):
    return state["round"]["headline"]["text"]


def lie(text: str) -> str:
    """A one-word lie the mock judge will accept: negate or bump something."""
    words = text.split()
    for i, w in enumerate(words):
        if any(ch.isdigit() for ch in w):
            words[i] = "999"
            return " ".join(words)
    return " ".join(words[:1] + ["never"] + words[1:])


def test_health_reports_detector_and_judge(client):
    body = client.get("/api/health").json()
    assert body["detector"] == "stub" and body["judge"] == "mock" and body["headlines"] > 50


def test_run_starts_with_full_lives_and_a_round(client):
    _, state = new_run(client)
    assert state["run"]["lives"] == 3 and state["run"]["score"] == 0
    assert state["round"]["status"] == "active"
    assert state["round"]["timer_start_s"] >= 10
    assert state["round"]["headline"]["snippet"]


def test_live_meter_reports_changes_and_suspicion(client):
    pid, state = new_run(client)
    rid, text = state["round"]["id"], headline_of(state)
    body = client.post(f"/api/round/{rid}/suspicion",
                       json={"player_id": pid, "edited": lie(text)}).json()
    assert 0.0 <= body["suspicion"] <= 1.0
    assert body["num_changes"] == 1 and not body["over_limit"]


def test_too_many_changes_is_rejected_without_using_an_attempt(client):
    pid, state = new_run(client)
    rid = state["round"]["id"]
    r = client.post(f"/api/round/{rid}/submit",
                    json={"player_id": pid, "edited": "a completely different headline about cats"})
    assert r.status_code == 400 and "limit" in r.json()["detail"]
    with SessionLocal() as db:
        assert db.get(Round, rid).attempts_used == 0


def test_unchanged_headline_is_rejected(client):
    pid, state = new_run(client)
    r = client.post(f"/api/round/{state['round']['id']}/submit",
                    json={"player_id": pid, "edited": headline_of(state)})
    assert r.status_code == 400


def test_a_valid_lie_is_judged_scored_and_logged(client):
    pid, state = new_run(client)
    rid = state["round"]["id"]
    trace = [{"t_ms": 400, "s": 0.2}, {"t_ms": 900, "s": 0.31}]
    body = client.post(f"/api/round/{rid}/submit", json={
        "player_id": pid, "edited": lie(headline_of(state)), "trace": trace,
        "time_to_submit_ms": 950}).json()
    assert body["outcome"] in {"snuck", "caught"}
    assert body["verdict"]["judge"] == "mock" and body["verdict"]["is_false"]
    run = body["state"]["run"]
    if body["outcome"] == "snuck":
        assert body["points"]["total"] > 0 and run["streak"] == 1 and run["lives"] == 3
    else:
        assert run["lives"] == 2 and run["streak"] == 0
    with SessionLocal() as db:
        att = db.query(Attempt).filter(Attempt.round_id == rid).one()
        assert att.num_words_changed == 1 and att.detector_version == "stub"
        assert att.suspicion_trace_json and att.timer_start_seconds > 0
        assert not att.timed_out and att.time_to_submit_ms == 950


def test_three_invalid_attempts_exhaust_the_round_without_losing_a_life(client):
    fillers = {"to", "in", "of", "the", "a", "for", "on"}
    for _ in range(30):                     # deal until a headline has a function word
        pid, state = new_run(client)
        words = headline_of(state).split()
        if any(w.lower() in fillers for w in words):
            break
    rid, text = state["round"]["id"], headline_of(state)
    # A harmless edit: duplicate-free, plausible, but changes only a function word.
    first = next(i for i, w in enumerate(words) if w.lower() in fillers)
    bodies = []
    for filler in ("the", "a", "of"):
        edited = " ".join(words[:first] + [filler] + words[first + 1:])
        if edited == text:
            continue
        bodies.append(client.post(f"/api/round/{rid}/submit",
                                  json={"player_id": pid, "edited": edited}).json())
        if bodies[-1].get("round_over"):
            break
    assert all(b["outcome"] == "invalid" for b in bodies)
    last = bodies[-1]
    if last["round_over"]:
        assert last["state"]["run"]["lives"] == 3 and "exhausted" in last["events"]


def test_timeout_costs_a_life_and_is_logged(client):
    pid, state = new_run(client)
    rid = state["round"]["id"]
    early = client.post(f"/api/round/{rid}/timeout", json={"player_id": pid})
    assert early.status_code == 409                      # clock not run out yet
    with SessionLocal() as db:                           # wind the clock past zero
        rnd = db.get(Round, rid)
        rnd.started_at -= timedelta(seconds=rnd.timer_start_s + 5)
        db.commit()
    body = client.post(f"/api/round/{rid}/timeout",
                       json={"player_id": pid, "edited": headline_of(state)}).json()
    assert body["outcome"] == "timeout" and "times_up" in body["events"]
    assert body["state"]["run"]["lives"] == 2
    with SessionLocal() as db:
        att = db.query(Attempt).filter(Attempt.round_id == rid).one()
        assert att.timed_out and att.outcome == "timeout"


def test_late_submit_counts_as_timeout(client):
    pid, state = new_run(client)
    rid = state["round"]["id"]
    with SessionLocal() as db:
        rnd = db.get(Round, rid)
        rnd.started_at -= timedelta(seconds=rnd.timer_start_s + 10)
        db.commit()
    body = client.post(f"/api/round/{rid}/submit",
                       json={"player_id": pid, "edited": lie(headline_of(state))}).json()
    assert body["outcome"] == "timeout"


def test_losing_all_lives_ends_the_run(client):
    pid, state = new_run(client)
    run_id = state["run"]["id"]
    for _ in range(3):
        rid = state["round"]["id"]
        with SessionLocal() as db:
            rnd = db.get(Round, rid)
            rnd.started_at -= timedelta(seconds=rnd.timer_start_s + 5)
            db.commit()
        body = client.post(f"/api/round/{rid}/timeout", json={"player_id": pid}).json()
        if body["run_over"]:
            break
        state = client.post(f"/api/run/{run_id}/next", json={"player_id": pid}).json()
    assert body["run_over"] and body["state"]["run"]["over"]
    assert client.post(f"/api/run/{run_id}/next", json={"player_id": pid}).status_code == 409


def test_cannot_play_someone_elses_round(client):
    _, state = new_run(client, "Alice")
    bob = client.post("/api/player", json={"name": "Bob"}).json()["player_id"]
    r = client.post(f"/api/round/{state['round']['id']}/submit",
                    json={"player_id": bob, "edited": lie(headline_of(state))})
    assert r.status_code == 403


def test_bounties_are_flagged_by_the_current_detector(client):
    with SessionLocal() as db:
        assert db.query(Headline).filter(Headline.is_bounty).count() > 0
    assert registry.current_name() == "stub"


def test_first_exploit_is_a_zero_day_and_reaches_the_board(client):
    from app import novelty
    if not novelty.available():
        pytest.skip("sentence-transformers not installed")
    from app import config
    old = config.SNEAK_THRESHOLD
    config.SNEAK_THRESHOLD = 1.01          # make sure this one sneaks past
    try:
        pid, state = new_run(client, "Novel")
        body = client.post(f"/api/round/{state['round']['id']}/submit", json={
            "player_id": pid, "edited": lie(headline_of(state))}).json()
    finally:
        config.SNEAK_THRESHOLD = old
    assert body["outcome"] == "snuck"
    with SessionLocal() as db:
        att = db.query(Attempt).order_by(Attempt.id.desc()).first()
        assert att.novelty_distance is not None and att.edit_embedding_json
    board = client.get("/api/exploits").json()
    assert board["label"].startswith("FAKE")
    assert all(r["label"].startswith("FAKE") for r in board["rows"])
    if att.is_novel:
        assert "zero_day" in body["events"] and body["points"]["novelty_mult"] == 1.5
        assert any(r["id"] == att.id for r in board["rows"])


def _fake_exploits(n: int, judge: str = "claude") -> str:
    """Insert ``n`` judge-verified exploits for a fresh player; return the player id."""
    import json
    import uuid
    from app.models import Player, Run
    from app.models import Round as RoundRow
    with SessionLocal() as db:
        pid = uuid.uuid4().hex[:24]
        db.add(Player(id=pid, name="Patchee"))
        run = Run(id=uuid.uuid4().hex[:20], player_id=pid, lives=3, detector_version="stub")
        db.add(run)
        heads = db.query(Headline).filter(Headline.active).limit(n).all()
        for h in heads:
            rnd = RoundRow(id=uuid.uuid4().hex[:20], run_id=run.id, headline_id=h.id,
                           timer_start_s=20, status="snuck")
            db.add(rnd)
            db.flush()
            db.add(Attempt(round_id=rnd.id, run_id=run.id, player_id=pid, attempt_no=1,
                           headline_id=h.id, original_headline=h.text,
                           edited_headline=lie(h.text), outcome="snuck", points=100,
                           detector_version="stub", suspicion_score_final=0.2,
                           judge_output_json=json.dumps({"judge": judge, "is_false": True})))
        db.commit()
    return pid


def test_patch_day_refuses_without_enough_exploits(client):
    from detector import patch_day
    result = patch_day.run(min_exploits=10_000)
    assert not result["shipped"] and "need" in result["reason"]


def test_patch_day_ignores_mock_judged_exploits_by_default(client):
    from detector import patch_day
    _fake_exploits(12, judge="mock")
    before = len(patch_day.exploits(SessionLocal(), include_mock=False))
    with_mock = len(patch_day.exploits(SessionLocal(), include_mock=True))
    assert with_mock >= before + 12


def test_patch_day_ships_a_version_and_notifies_players(client):
    from detector import patch_day
    from ingest.make_fakes import generate
    generate(use_rules=True)                 # the ship gate needs held-out fakes to check against
    pid = _fake_exploits(20)
    result = patch_day.run(min_exploits=5, log=lambda *_: None)
    assert result["shipped"], result.get("reason")
    assert result["name"].startswith("v")
    assert registry.current_name() == result["name"]
    assert result["holdout_catch_after"] is None or 0 <= result["holdout_catch_after"] <= 1
    assert client.get("/api/health").json()["detector"] == result["name"]
    versions = client.get("/api/detector/versions").json()
    assert versions["current"] == result["name"]
    notices = client.get(f"/api/player/{pid}/notices").json()["notices"]
    if result.get("newly_patched"):
        assert notices and all(n["label"].startswith("FAKE") for n in notices)
        assert client.get(f"/api/player/{pid}/notices").json()["notices"] == []   # shown once
    registry.set_current("stub")


def test_admin_patch_day_needs_the_token(client):
    assert client.post("/api/admin/patch-day").status_code == 401


def test_analytics_has_every_dashboard_section(client):
    body = client.get("/api/analytics").json()
    assert {"totals", "versions", "edit_types", "words_added", "timer", "mock_judged_attempts"} <= body.keys()
    assert [b["bucket"] for b in body["timer"]] == ["0–25%", "25–50%", "50–75%", "75–100%"]
    assert any(v["name"] == "stub" for v in body["versions"])
    real = client.get("/api/analytics?judge=real").json()
    assert real["totals"]["attempts"] <= body["totals"]["attempts"]
    assert client.get("/api/analytics?judge=bogus").status_code == 422
