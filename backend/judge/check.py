"""Check the judge works with your key before players hit it.

    python -m judge.check

Shows which provider and model the game will use, lists the chat models your
OpenAI key can see (to pick SIP_OPENAI_JUDGE_MODEL / SIP_OPENAI_FAKES_MODEL),
and judges two sample edits -- one real lie, one harmless rewording -- so you
can see a verdict and how long it takes.
"""

from __future__ import annotations

import os
import time

from app import config

from . import get_judge
from .base import JudgeUnavailable

ORIGINAL = "Storm Boelo to bring 80mph gusts and heavy rain to parts of UK"
SNIPPET = "Second named storm will hit northern parts of the UK as thousands remain without power."
SAMPLES = [
    ("a lie (should be is_false=true)", "Storm Boelo to bring 180mph gusts and heavy rain to parts of UK"),
    ("a rewording (should be is_false=false)", "Storm Boelo set to bring 80mph gusts and heavy rain to parts of UK"),
]


def main() -> None:
    judge = get_judge()
    print(f"judge: {judge.name}  model: {getattr(judge, 'model', '-')}")
    if judge.name == "mock":
        print("No ANTHROPIC_API_KEY or OPENAI_API_KEY found (checked the environment and .env).")
    if os.environ.get("OPENAI_API_KEY"):
        try:
            import openai
            names = sorted(m.id for m in openai.OpenAI().models.list() if m.id.startswith(("gpt", "o")))
            print(f"OpenAI models your key can use ({len(names)}): {', '.join(names[:40])}")
            for label, model in (("judge", config.OPENAI_JUDGE_MODEL), ("fakes", config.OPENAI_FAKES_MODEL)):
                if model not in names:
                    print(f"  ! {label} model {model!r} is not in that list; set SIP_OPENAI_"
                          f"{label.upper()}_MODEL in .env to one that is")
        except Exception as exc:  # noqa: BLE001 - diagnostics, report and carry on
            print(f"could not list OpenAI models: {type(exc).__name__}: {exc}")
    for label, edited in SAMPLES:
        t0 = time.monotonic()
        try:
            v = judge.judge(ORIGINAL, SNIPPET, edited)
        except JudgeUnavailable as exc:
            print(f"{label}: UNAVAILABLE ({exc})")
            continue
        print(f"{label}: is_false={v.is_false} plausible={v.is_plausible} "
              f"grammatical={v.is_grammatical} type={v.edit_type!r} "
              f"({time.monotonic() - t0:.1f}s)\n    {v.explanation}")


if __name__ == "__main__":
    main()
