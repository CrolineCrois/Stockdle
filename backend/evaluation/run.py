"""Run the controlled comparison and save the results.

    python -m evaluation.run                    # approved exploits only
    python -m evaluation.run --vitaminc 1000    # bigger external sample
    python -m evaluation.run --dev              # include pending exploits (NOT research data)

Models -- all from the same base, same training settings, same number of
training examples:

    v0             the off-the-shelf verifier, no fine-tuning
    v1-synthetic   CONTROL: LLM-written edits of the same training headlines,
                   matched to the human edit-type mix, same judge filters
    v1-human       approved human exploits
    v1-combined    half human + half synthetic (same total)

Each also gets the matched true headlines (SUPPORTED). Results go to
``data/eval/results/<timestamp>.json`` and ``data/eval/latest.json``, which
the /lab dashboard reads. Small or negative results are reported as they are.
"""

from __future__ import annotations

import argparse
import json
import random
from datetime import datetime, timezone

from app import config
from app.db import init_db
from verifier import registry
from verifier.model import VerifierModel
from verifier.train import SETTINGS, Example, finetune

from .data import EVAL_DIR, human_sets, pick_provider, synthetic_control, vitaminc
from .metrics import score_all

MODEL_DIR = config.DATA_DIR / "verifiers"


def _train(name: str, lies: list[Example], truths: list[Example], train_data: str, log,
           epochs: int = SETTINGS["epochs"]) -> VerifierModel:
    examples = lies + truths
    random.Random(SETTINGS["seed"]).shuffle(examples)
    log(f"[eval] training {name}: {len(lies)} false + {len(truths)} true examples")
    model = finetune(name, config.VERIFIER_BASE_MODEL, examples, MODEL_DIR / name, epochs=epochs,
                     log=log)
    registry.register(name, str(MODEL_DIR / name), train_data=train_data, n_train=len(examples),
                      metrics={}, note=f"evaluation model ({train_data})", make_current=False)
    return model


def run(*, dev: bool = False, vitaminc_n: int = 500, min_train: int = 10,
        skip_synthetic: bool = False, epochs: int = SETTINGS["epochs"], log=print) -> dict:
    init_db()
    sets = human_sets(include_pending=dev)
    human_train = sets["train"]
    if len(human_train) < min_train:
        raise SystemExit(f"only {len(human_train)} training exploits (need {min_train}); "
                         "approve more on /admin, or use --dev to include pending ones")
    lies_h = [ex for ex, _ in human_train]
    truths = sets["train_true"]
    n = len(lies_h)

    synth: list[Example] = []
    provider = None
    if not skip_synthetic:
        provider = pick_provider()
        synth = synthetic_control(human_train, provider, log=log)

    vc = vitaminc(vitaminc_n) if vitaminc_n else []
    models = {"v0": registry.load("v0")}
    models["v1-human"] = _train("v1-human", lies_h, truths, "human", log, epochs)
    if synth:
        # Same count as human: if the control came up short, say so in the results.
        models["v1-synthetic"] = _train("v1-synthetic", synth[:n], truths, "synthetic", log, epochs)
        half = n // 2
        models["v1-combined"] = _train("v1-combined", lies_h[:n - half] + synth[:half], truths,
                                       "combined", log, epochs)

    results = {"created_at": datetime.now(timezone.utc).isoformat(), "dev_data": dev,
               "base_model": config.VERIFIER_BASE_MODEL, "settings": {**SETTINGS, "epochs": epochs},
               "retrieval_top_k": config.VERIFIER_TOP_K, "split": sets["split"],
               "counts": {"train_exploits": n, "train_true": len(truths),
                          "synthetic_control": len(synth[:n]),
                          "test_exploits": len(sets["test"]), "fresh_exploits": len(sets["fresh"]),
                          "true_test": len(sets["true_test"]), "vitaminc": len(vc)},
               "synthetic_provider": provider, "models": {}}
    for name, model in models.items():
        log(f"[eval] scoring {name}")
        results["models"][name] = score_all(model, sets, vc)
        if name != "v0":
            registry.evict(name)

    out = EVAL_DIR / "results"
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    (out / f"{stamp}.json").write_text(json.dumps(results, indent=1))
    (EVAL_DIR / "latest.json").write_text(json.dumps(results, indent=1))
    _print(results, log)
    return results


def _fmt(m: dict) -> str:
    if m.get("value") is None:
        return "   —        "
    return f"{m['value']:.2f} [{m['lo']:.2f},{m['hi']:.2f}]"


def _print(r: dict, log) -> None:
    log("\n[eval] refute recall (held-out exploits) | false positives (true) | fresh | VitaminC macro-F1")
    for name, m in r["models"].items():
        log(f"  {name:13} {_fmt(m['held_out_exploits']['overall'])}  "
            f"{_fmt(m['true_headlines']['overall'])}  {_fmt(m['fresh_exploits']['overall'])}  "
            f"{_fmt(m['vitaminc']['macro_f1'])}")
    if r["dev_data"]:
        log("  (dev run: includes unreviewed exploits — not research data)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dev", action="store_true", help="include pending (unreviewed) exploits")
    ap.add_argument("--vitaminc", type=int, default=500)
    ap.add_argument("--min-train", type=int, default=10)
    ap.add_argument("--skip-synthetic", action="store_true")
    ap.add_argument("--epochs", type=int, default=SETTINGS["epochs"])
    a = ap.parse_args()
    run(dev=a.dev, vitaminc_n=a.vitaminc, min_train=a.min_train, skip_synthetic=a.skip_synthetic,
        epochs=a.epochs)


if __name__ == "__main__":
    main()
