"""Detector plumbing: evaluation maths and version switching (no model download)."""

from app.db import init_db
from detector import registry
from detector.evaluate import catch_rate, metrics


class Fixed:
    """A detector that returns preset scores, keyed by headline."""

    name, kind = "fixed", "test"

    def __init__(self, scores):
        self.scores = scores

    def predict(self, pairs):
        return [self.scores[h] for h, _ in pairs]


def test_metrics_counts_catches_and_false_alarms():
    det = Fixed({"t1": 0.1, "t2": 0.7, "f1": 0.9, "f2": 0.4})
    m = metrics(det, [("t1", ""), ("t2", ""), ("f1", ""), ("f2", "")], [0, 0, 1, 1])
    assert m["catch_rate"] == 0.5 and m["false_alarm_rate"] == 0.5
    assert m["accuracy"] == 0.5 and 0 <= m["auc"] <= 1


def test_catch_rate_on_fakes_only():
    assert catch_rate(Fixed({"a": 0.6, "b": 0.2}), [("a", ""), ("b", "")]) == 0.5
    assert catch_rate(Fixed({}), []) is None


def test_set_current_switches_the_live_version(tmp_path):
    init_db()
    registry.register("vtest-a", "baseline", tmp_path, n_train=1, metrics={}, note="",
                      make_current=False)
    registry.register("vtest-b", "baseline", tmp_path, n_train=1, metrics={}, note="",
                      make_current=True)
    assert registry.current_name() == "vtest-b"
    registry.set_current("vtest-a")
    assert registry.current_name() == "vtest-a"
    names = [v.name for v in registry.versions()]
    assert "vtest-a" in names and "vtest-b" in names
