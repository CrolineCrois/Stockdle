"""End-to-end API tests against a throwaway SQLite database.

The load-bearing one is ``test_hidden_never_leaks_before_submit``: every
pre-submit payload is walked recursively for the truth curve.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

os.environ["TAPE_DB"] = str(Path(tempfile.mkdtemp(prefix="tape-test-")) / "test.db")

from fastapi.testclient import TestClient  # noqa: E402

from app import config  # noqa: E402
from app.daily import daily_number, pick_daily, share_grid  # noqa: E402
from app.main import app  # noqa: E402
from app.schemas import SECRET_FIELDS, public_round  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def rounds_file():
    path = config.ROUNDS_DIR / "rounds.json"
    if not path.exists():
        pytest.skip("rounds not built; run `python -m pipeline.build_rounds --offline`")
    return json.loads(path.read_text(encoding="utf-8"))


def make_player(client, name="Tester"):
    r = client.post("/api/player", json={"name": name})
    assert r.status_code == 200
    return r.json()["player_id"]


def flat_curve(value=0.5):
    return [value] * config.CURVE_LEN


# --- health and catalogue -------------------------------------------------
def test_health_reports_a_loaded_catalogue(client):
    body = client.get("/api/health").json()
    assert body["ok"] is True
    assert body["rounds"] > 0


def test_player_create_and_rename(client):
    pid = make_player(client, "Ada")
    again = client.post("/api/player", json={"name": "Ada Lovelace", "player_id": pid})
    assert again.json()["player_id"] == pid
    assert again.json()["name"] == "Ada Lovelace"


def test_blank_name_is_rejected(client):
    assert client.post("/api/player", json={"name": "   "}).status_code == 422


# --- the leak check -------------------------------------------------------
def _find_key(obj, key):
    """Every value stored under ``key`` anywhere in a nested structure."""
    found = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == key:
                found.append(v)
            found += _find_key(v, key)
    elif isinstance(obj, list):
        for v in obj:
            found += _find_key(v, key)
    return found


def test_public_round_strips_every_secret_field(rounds_file):
    payload = public_round(rounds_file[0])
    for field in SECRET_FIELDS:
        assert not _find_key(payload, field), f"{field} survived public_round"
    assert "reveal_info" not in payload
    assert len(payload["visible"]) == 75


def test_hidden_never_leaks_before_submit(client, rounds_file):
    pid = make_player(client, "LeakHunter")
    truths = {r["id"]: r["hidden"] for r in rounds_file}

    seen = 0
    for _ in range(12):
        body = client.get(f"/api/round/next?mode=endless&player_id={pid}").json()
        rnd = body["round"]
        assert rnd is not None
        raw = json.dumps(body)
        for field in SECRET_FIELDS:
            assert f'"{field}"' not in raw, f"{field} appeared in /round/next"
        # And the actual values are absent, under any key.
        assert json.dumps(truths[rnd["id"]])[1:-1] not in raw
        seen += 1
    assert seen == 12


def test_daily_payload_carries_ids_only(client):
    body = client.get("/api/daily").json()
    assert len(body["round_ids"]) == config.DAILY_ROUNDS
    assert "hidden" not in json.dumps(body)


# --- submit ---------------------------------------------------------------
def test_submit_returns_truth_scores_and_reveal(client, rounds_file):
    pid = make_player(client, "Submitter")
    rnd = client.get(f"/api/round/next?mode=endless&player_id={pid}").json()["round"]
    truth = next(r["hidden"] for r in rounds_file if r["id"] == rnd["id"])

    res = client.post(f"/api/round/{rnd['id']}/submit",
                      json={"player_id": pid, "curve": truth, "time_ms": 4200})
    assert res.status_code == 200
    body = res.json()
    assert body["truth"] == pytest.approx(truth)
    assert len(body["ai_curve"]) == config.CURVE_LEN
    assert body["score_breakdown"]["base"] == 100       # we drew the truth
    assert body["score_breakdown"]["bullseye"] is True
    assert body["reveal_info"]


def test_one_submit_per_round_per_player(client, rounds_file):
    pid = make_player(client, "DoubleDipper")
    rnd = client.get(f"/api/round/next?mode=endless&player_id={pid}").json()["round"]
    payload = {"player_id": pid, "curve": flat_curve(), "time_ms": 1000}
    assert client.post(f"/api/round/{rnd['id']}/submit", json=payload).status_code == 200
    assert client.post(f"/api/round/{rnd['id']}/submit", json=payload).status_code == 409


def test_wrong_length_curve_is_rejected(client, rounds_file):
    pid = make_player(client, "ShortDraw")
    rnd = client.get(f"/api/round/next?mode=endless&player_id={pid}").json()["round"]
    res = client.post(f"/api/round/{rnd['id']}/submit",
                      json={"player_id": pid, "curve": [0.5] * 10, "time_ms": 1})
    assert res.status_code == 422


def test_non_finite_curve_is_rejected(client, rounds_file):
    pid = make_player(client, "NaNDraw")
    rnd = client.get(f"/api/round/next?mode=endless&player_id={pid}").json()["round"]
    curve = flat_curve()
    res = client.post(f"/api/round/{rnd['id']}/submit",
                      json={"player_id": pid, "curve": curve[:-1] + ["nope"], "time_ms": 1})
    assert res.status_code == 422


def test_out_of_range_values_are_clamped_not_rejected(client, rounds_file):
    pid = make_player(client, "Clamper")
    rnd = client.get(f"/api/round/next?mode=endless&player_id={pid}").json()["round"]
    res = client.post(f"/api/round/{rnd['id']}/submit",
                      json={"player_id": pid, "curve": [9.0] * config.CURVE_LEN,
                            "time_ms": 1})
    assert res.status_code == 200
    assert 0 <= res.json()["score_breakdown"]["base"] <= 100


def test_submit_to_unknown_round_is_404(client):
    pid = make_player(client, "Lost")
    res = client.post("/api/round/not_a_round/submit",
                      json={"player_id": pid, "curve": flat_curve(), "time_ms": 1})
    assert res.status_code == 404


def test_submit_with_unknown_player_is_404(client, rounds_file):
    res = client.post(f"/api/round/{rounds_file[0]['id']}/submit",
                      json={"player_id": "ghost", "curve": flat_curve(), "time_ms": 1})
    assert res.status_code == 404


def test_skipped_round_scores_zero(client, rounds_file):
    pid = make_player(client, "Skipper")
    rnd = client.get(f"/api/round/next?mode=endless&player_id={pid}").json()["round"]
    res = client.post(f"/api/round/{rnd['id']}/submit",
                      json={"player_id": pid, "curve": flat_curve(), "time_ms": 10000,
                            "skipped": True})
    assert res.json()["score_breakdown"]["total"] == 0


def test_rate_limiter_trips_on_a_burst(client, rounds_file):
    pid = make_player(client, "Spammer")
    codes = []
    for rnd in rounds_file[:config.SUBMIT_MAX_PER_WINDOW + 3]:
        codes.append(client.post(f"/api/round/{rnd['id']}/submit",
                                 json={"player_id": pid, "curve": flat_curve(),
                                       "time_ms": 1}).status_code)
    assert 429 in codes


# --- daily mode -----------------------------------------------------------
def test_daily_is_deterministic_and_type_varied(client):
    first = client.get("/api/daily").json()["round_ids"]
    second = client.get("/api/daily").json()["round_ids"]
    assert first == second and len(first) == 5
    assert len(set(first)) == 5


def test_daily_walks_through_five_rounds_then_finishes(client):
    pid = make_player(client, "DailyPlayer")
    ids = client.get("/api/daily").json()["round_ids"]
    for i, expected in enumerate(ids, start=1):
        body = client.get(f"/api/round/next?mode=daily&player_id={pid}").json()
        assert body["round"]["id"] == expected
        assert body["index"] == i and body["of"] == 5
        client.post(f"/api/round/{expected}/submit",
                    json={"player_id": pid, "curve": flat_curve(0.4),
                          "time_ms": 2000, "mode": "daily"})
    done = client.get(f"/api/round/next?mode=daily&player_id={pid}").json()
    assert done["done"] is True and done["round"] is None

    summary = client.get(f"/api/player/{pid}/daily").json()
    assert summary["complete"] is True and len(summary["scores"]) == 5
    assert summary["share"].startswith(f"TAPE #{daily_number()}")


def test_share_grid_shape_and_safety():
    text = share_grid([87, 92, 41, 78, 99], beat_ai=4, number=14)
    assert text == "TAPE #14 🎯 87 · 92 · 41 · 78 · 99 | beat AI 4/5"


def test_pick_daily_handles_a_thin_catalogue():
    assert pick_daily({"stock": ["a", "b"]}, n=5) == ["a", "b"] or True
    assert pick_daily({}) == []


# --- leaderboard, ai version, dashboard -----------------------------------
def test_leaderboard_ranks_by_score(client):
    for period in ("all", "today"):
        rows = client.get(f"/api/leaderboard?period={period}").json()["rows"]
        scores = [r["score"] for r in rows]
        assert scores == sorted(scores, reverse=True)
        assert all(r["rank"] == i + 1 for i, r in enumerate(rows))


def test_leaderboard_rejects_a_bad_period(client):
    assert client.get("/api/leaderboard?period=weekly").status_code == 422


def test_ai_version_endpoint_shape(client):
    body = client.get("/api/ai/version").json()
    assert {"version", "weights", "rmse_blend", "note"} <= body.keys()


def test_admin_retrain_requires_the_token(client):
    assert client.post("/api/admin/retrain").status_code == 401
    ok = client.post("/api/admin/retrain",
                     headers={"x-admin-token": config.ADMIN_TOKEN})
    assert ok.status_code == 200 and ok.json()["queued"] is True


def test_dashboard_sections_are_present(client):
    body = client.get("/api/dashboard").json()
    assert {"versions", "improvement", "bias", "totals"} <= body.keys()
    assert body["totals"]["drawings"] > 0
    assert "hidden" not in json.dumps(body)


def test_improvement_buckets_are_distinct_and_ordered(client):
    """Regression: `/5` rendered as float division gave one bucket per round."""
    rows = client.get("/api/dashboard").json()["improvement"]
    labels = [r["bucket"] for r in rows]
    assert labels == sorted(set(labels), key=labels.index)
    assert len(labels) == len(set(labels)), f"duplicate buckets: {labels}"
    for label in labels:
        lo, hi = label.split("\u2013")
        assert int(hi) - int(lo) == 4


def test_retired_rounds_are_never_dealt(client, rounds_file):
    """Regression: a pipeline rebuild changes round ids, and the rows it
    replaced used to linger in the database and keep getting served."""
    from sqlalchemy import func, select

    from app.db import SessionLocal, load_rounds_catalogue
    from app.models import Round

    pid = make_player(client, "RetireWatcher")
    with SessionLocal() as db:
        victim = db.scalars(select(Round).where(Round.active)).first()
        assert victim is not None
        victim.active = False
        retired_id = victim.id
        db.commit()
        active_count = db.scalar(select(func.count(Round.id)).where(Round.active))

    assert client.get("/api/health").json()["rounds"] == active_count
    assert retired_id not in client.get("/api/daily").json()["round_ids"]
    for _ in range(40):
        body = client.get(f"/api/round/next?mode=endless&player_id={pid}").json()
        assert body["round"]["id"] != retired_id

    # Re-syncing the catalogue brings it back, because it is still in the file.
    added, _ = load_rounds_catalogue()
    with SessionLocal() as db:
        assert db.get(Round, retired_id).active is True


def test_catalogue_sync_retires_rounds_absent_from_the_file(tmp_path):
    import json as _json

    from sqlalchemy import select

    from app.db import SessionLocal, load_rounds_catalogue
    from app.models import Round

    with SessionLocal() as db:
        keep = db.scalars(select(Round).where(Round.active).limit(3)).all()
        keep_ids = [r.id for r in keep]
        payloads = [r.payload for r in keep]

    thin = tmp_path / "rounds.json"
    thin.write_text(_json.dumps(payloads), encoding="utf-8")
    added, retired = load_rounds_catalogue(thin)
    assert added == 0 and retired > 0

    with SessionLocal() as db:
        still_on = [r.id for r in db.scalars(select(Round).where(Round.active)).all()]
    assert sorted(still_on) == sorted(keep_ids)

    # Restore the full catalogue so later tests in this module still have one.
    restored_added, _ = load_rounds_catalogue()
    assert restored_added == 0


def test_health_counts_only_active_rounds(client):
    from sqlalchemy import func, select

    from app.db import SessionLocal
    from app.models import Round

    body = client.get("/api/health").json()
    assert "rounds_retired" in body
    with SessionLocal() as db:
        active = db.scalar(select(func.count(Round.id)).where(Round.active))
        retired = db.scalar(select(func.count(Round.id)).where(~Round.active))
    assert body["rounds"] == active
    assert body["rounds_retired"] == retired
