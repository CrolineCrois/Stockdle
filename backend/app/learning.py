"""How the AI is doing, and how each version compares with the last.

Two kinds of numbers:

    benchmark  every version of a model scored on the SAME fixed held-out set,
               so versions are comparable: machine-written lies caught, true
               headlines wrongly flagged (95% bootstrap intervals). Stored on the
               version row once, recomputed only if the set changes.
                 - fact-checker: the evaluation split's TEST headlines (no
                   verifier version trains on them) and their LLM-written fakes
                 - meter: the meter split's test headlines (no meter version
                   trains on them) and their LLM-written fakes
    live       how the fact-checker actually did against players: of the
               judge-valid lies played against each version, the share it
               refuted (caught).

    python -m app.learning      # (re)benchmark every version
"""

from __future__ import annotations

import json

from sqlalchemy import select

from detector import registry as meters
from detector.premise import premise_for
from verifier import registry as verifiers
from verifier.model import aggregate
from verifier.retrieval import retrieve

from . import config
from .db import SessionLocal, init_db
from .models import Attempt, DetectorVersion, Headline, SyntheticFake, VerifierVersion

LLM_GENERATORS = ("openai", "claude")


def _sets(db, test_ids: set[int]) -> tuple[list[tuple[str, int]], list[tuple[str, int]]]:
    heads = db.scalars(select(Headline).where(Headline.id.in_(test_ids), Headline.active)).all()
    trues = [(h.text, h.id) for h in heads]
    fakes = [(f.text, f.headline_id) for f in db.scalars(select(SyntheticFake).where(
        SyntheticFake.headline_id.in_(test_ids), SyntheticFake.generator.in_(LLM_GENERATORS))).all()]
    return trues, fakes


def _verifier_test_ids(db) -> set[int]:
    from evaluation.data import load_split
    heads = db.scalars(select(Headline.id).where(Headline.active)).all()
    return {int(k) for k, v in load_split(list(heads))["sides"].items() if v == "test"}


def _meter_test_ids(db) -> set[int]:
    from detector.splits import load_split
    return set(load_split(list(db.scalars(select(Headline).where(Headline.active)).all())))


def _summary(caught_fakes: list[float], flagged_trues: list[float], key: tuple) -> dict:
    from evaluation.metrics import ci
    return {"lies_caught": ci(caught_fakes), "true_flagged": ci(flagged_trues), "set": list(key)}


def benchmark_verifier(name: str, force: bool = False) -> dict:
    from evaluation.data import human_sets
    from evaluation.metrics import refute_recall
    human_test = human_sets(include_pending=False)["test"]   # approved, test-side headlines
    with SessionLocal() as db:
        ids = _verifier_test_ids(db)
        trues, fakes = _sets(db, ids)
        row = db.scalar(select(VerifierVersion).where(VerifierVersion.name == name))
        metrics = json.loads(row.metrics_json or "{}")
        key = (len(trues), len(fakes), len(human_test), config.VERIFIER_RULE)
        if not force and metrics.get("benchmark", {}).get("set") == list(key):
            return metrics["benchmark"]
    model = verifiers.load(name)

    def refuted(claim: str, hid: int) -> float:
        hits = retrieve(claim)
        return float(aggregate(model.score(claim, [h.text for h in hits]),
                               passage_sources=[h.headline_id for h in hits], source=hid)[0] == "refuted")

    bench = _summary([refuted(c, h) for c, h in fakes], [refuted(c, h) for c, h in trues], key)
    # Players' approved lies on headlines no version trains on. They all fooled
    # v0 when played (that's what makes them exploits), so v0 scores near zero
    # by construction; later versions are the honest comparison.
    bench["human_lies_caught"] = refute_recall(model, human_test)["overall"] if human_test else None
    with SessionLocal() as db:
        row = db.scalar(select(VerifierVersion).where(VerifierVersion.name == name))
        m = json.loads(row.metrics_json or "{}")
        m["benchmark"] = bench
        row.metrics_json = json.dumps(m)
        db.commit()
    if name != verifiers.current_name():
        verifiers.evict(name)
    return bench


def benchmark_meter(name: str, force: bool = False) -> dict:
    with SessionLocal() as db:
        ids = _meter_test_ids(db)
        trues, fakes = _sets(db, ids)
        row = db.scalar(select(DetectorVersion).where(DetectorVersion.name == name))
        metrics = json.loads(row.metrics_json or "{}")
        key = (len(trues), len(fakes))
        if not force and metrics.get("benchmark", {}).get("set") == list(key):
            return metrics["benchmark"]
    det = meters.load(name)
    flag = lambda items: [float(p >= 0.5) for p in det.predict(  # noqa: E731
        [(c, premise_for(hid)) for c, hid in items])]
    bench = _summary(flag(fakes), flag(trues), key)
    with SessionLocal() as db:
        row = db.scalar(select(DetectorVersion).where(DetectorVersion.name == name))
        m = json.loads(row.metrics_json or "{}")
        m["benchmark"] = bench
        row.metrics_json = json.dumps(m)
        db.commit()
    return bench


GLANCE_FILE = "glance_benchmark.json"


def benchmark_glance(force: bool = False) -> dict:
    """The live meter in its default mode: the current verifier's P(refuted) on
    the single best source passage, on the meter's held-out set."""
    from . import config as cfg
    path = cfg.DATA_DIR / "eval" / GLANCE_FILE
    with SessionLocal() as db:
        trues, fakes = _sets(db, _meter_test_ids(db))
    key = [len(trues), len(fakes), verifiers.current_name()]
    if not force and path.exists():
        saved = json.loads(path.read_text())
        if saved.get("set") == key:
            return saved
    model = verifiers.current()
    flag = lambda items: [float(model.score(c, [premise_for(hid)])[0]["refuted"] >= 0.5)  # noqa: E731
                          for c, hid in items]
    bench = _summary(flag(fakes), flag(trues), tuple(key))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(bench))
    return bench


def live_by_verifier(db) -> list[dict]:
    """Of the judge-valid lies played against each verifier version, how many it caught."""
    from evaluation.metrics import ci
    rows = db.scalars(select(Attempt).where(Attempt.verifier_verdict.in_(("supported", "refuted", "nei")))).all()
    out = {}
    for a in rows:
        judge = json.loads(a.judge_output_json or "{}").get("judge")
        if judge == "mock":
            continue
        out.setdefault(a.verifier_version or "v0", []).append(float(a.verifier_verdict == "refuted"))
    return [{"version": k, "caught": ci(v)} for k, v in sorted(out.items())]


def summary() -> dict:
    """Everything the How-it-learns scorecard needs. Uses stored benchmarks only."""
    init_db()
    with SessionLocal() as db:
        vrows = db.scalars(select(VerifierVersion).order_by(VerifierVersion.created_at)).all()
        mrows = db.scalars(select(DetectorVersion).order_by(DetectorVersion.created_at)).all()
        live = live_by_verifier(db)
        cur_v, cur_m = verifiers.current_name(), meters.current_name()
        from . import config as cfg
        glance_live = cfg.METER != "style"
        meter_rows = [{"name": m.name, "n_train": m.n_train, "created_at": m.created_at.isoformat() + "Z",
                       "is_current": m.name == cur_m and not glance_live, "note": m.note,
                       "benchmark": json.loads(m.metrics_json or "{}").get("benchmark")}
                      for m in mrows if m.name == "stub" or m.name.startswith("v")]
        path = cfg.DATA_DIR / "eval" / GLANCE_FILE
        if path.exists():
            meter_rows.append({"name": f"glance ({cur_v})", "n_train": 0, "created_at": "",
                               "is_current": glance_live,
                               "note": "the fact-checker on the best source passage",
                               "benchmark": json.loads(path.read_text())})
        return {
            "verifier": [{"name": v.name, "train_data": v.train_data, "n_train": v.n_train,
                          "created_at": v.created_at.isoformat() + "Z", "is_current": v.name == cur_v,
                          "note": v.note,
                          "benchmark": json.loads(v.metrics_json or "{}").get("benchmark")}
                         for v in vrows if v.train_data in ("none", "human")],
            "meter": meter_rows,
            "live": live,
        }


def main() -> None:
    init_db()
    verifiers.ensure_v0()
    with SessionLocal() as db:
        vnames = [v.name for v in db.scalars(select(VerifierVersion)).all()
                  if v.train_data in ("none", "human")]
        mnames = [m.name for m in db.scalars(select(DetectorVersion)).all()
                  if m.name == "stub" or m.name.startswith("v")]
    for n in vnames:
        print(f"[bench] fact-checker {n}: {benchmark_verifier(n, force=True)}")
    for n in mnames:
        try:
            print(f"[bench] meter {n}: {benchmark_meter(n, force=True)}")
        except Exception as exc:  # noqa: BLE001 -- an old version whose files are gone
            print(f"[bench] meter {n}: skipped ({type(exc).__name__}: {exc})")
    print(f"[bench] meter glance: {benchmark_glance(force=True)}")


if __name__ == "__main__":
    main()
