"""Sanity-check plot: render a few built rounds to a PNG.

Visible half solid, the "now" cut as a dashed vertical, hidden half dotted.
This is the eyeball check for phase 1 -- if these look like plausible load
curves / price paths / search-interest seasons, the builder is behaving.

    python -m pipeline.plot_rounds
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from .common import HIDDEN_LEN, ROUNDS_DIR, VISIBLE_LEN, log, read_json  # noqa: E402

TYPE_COLOR = {"electricity": "#38bdf8", "stock": "#34d399",
              "trends": "#f472b6"}


def plot(out_name: str = "round_preview.png", per_type: int = 3) -> str:
    rounds = read_json(ROUNDS_DIR / "rounds.json") or []
    if not rounds:
        raise SystemExit("no rounds built yet; run `python -m pipeline.build_rounds`")

    chosen: list[dict] = []
    for kind in ("electricity", "stock", "trends"):
        chosen += [r for r in rounds if r["type"] == kind][:per_type]

    cols = per_type
    rows = (len(chosen) + cols - 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(5.2 * cols, 3.0 * rows),
                             facecolor="#0b1020")
    axes = np.atleast_1d(axes).ravel()

    for ax, r in zip(axes, chosen):
        colour = TYPE_COLOR.get(r["type"], "#e2e8f0")
        y_min, y_max = r["scale"]["y_min"], r["scale"]["y_max"]
        real = [y_min + v * (y_max - y_min) for v in r["visible"] + r["hidden"]]
        xs = np.arange(len(real))
        ax.plot(xs[:VISIBLE_LEN], real[:VISIBLE_LEN], color=colour, lw=1.9)
        ax.plot(xs[VISIBLE_LEN - 1:], real[VISIBLE_LEN - 1:], color=colour,
                lw=1.4, ls=":", alpha=0.85)
        ax.axvline(VISIBLE_LEN - 0.5, color="#64748b", ls="--", lw=1.0)
        ax.set_facecolor("#0b1020")
        ax.tick_params(colors="#94a3b8", labelsize=7)
        for spine in ax.spines.values():
            spine.set_color("#1e293b")
        title = r["context"]["title"]
        ax.set_title(f"{r['type']} · {r['source_key']}\n{title[:58]}",
                     color="#e2e8f0", fontsize=7.5)
        ax.set_ylabel(r["scale"]["y_label"], color="#94a3b8", fontsize=7)
        ax.grid(color="#1e293b", lw=0.5)

    for ax in axes[len(chosen):]:
        ax.axis("off")

    fig.suptitle(f"TAPE round preview — {len(rounds)} rounds built "
                 f"({VISIBLE_LEN} visible + {HIDDEN_LEN} hidden)",
                 color="#f8fafc", fontsize=11)
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    out = ROUNDS_DIR / out_name
    fig.savefig(out, dpi=120, facecolor="#0b1020")
    plt.close(fig)
    log(f"wrote {out}")
    return str(out)


if __name__ == "__main__":
    plot()
