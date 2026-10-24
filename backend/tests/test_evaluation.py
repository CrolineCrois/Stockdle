"""Evaluation maths and split stability (no model, no network)."""

from evaluation import data
from evaluation.metrics import ci


def test_ci_contains_the_point_and_is_ordered():
    m = ci([1.0] * 30 + [0.0] * 70)
    assert m["value"] == 0.3 and m["lo"] <= 0.3 <= m["hi"] and m["n"] == 100
    assert ci([])["value"] is None


def test_ci_narrows_with_more_data():
    small = ci([1.0, 0.0] * 10)
    big = ci([1.0, 0.0] * 500)
    assert (big["hi"] - big["lo"]) < (small["hi"] - small["lo"])


def test_split_is_by_headline_stable_and_about_30_percent(tmp_path, monkeypatch):
    monkeypatch.setattr(data, "EVAL_DIR", tmp_path)
    monkeypatch.setattr(data, "SPLIT_FILE", tmp_path / "split.json")
    first = data.load_split(list(range(1000)))["sides"]
    again = data.load_split(list(range(1500)))["sides"]
    assert all(again[k] == v for k, v in first.items())          # nobody moves sides
    share = sum(v == "test" for v in first.values()) / len(first)
    assert 0.25 < share < 0.35
