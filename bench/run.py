"""Runtime by scale, accuracy against ground truth, and IQR vs rule on price outliers.

uv run python -m bench.run
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import matplotlib.pyplot as plt
from shopflow_datagen import DirtyConfig, GenConfig, write

from bench.harness import RESULTS_DIR, machine_info, measure, save
from bench.plot import GRID, INK, INK_MUTED, SURFACE, plot
from data_quality_engine.engine import run
from data_quality_engine.evaluate import outlier_confusion, score_against_truth
from data_quality_engine.rules import load as load_rules

RULES = load_rules(Path("rules/shopflow.yml"))
SCALES = [1, 10, 50]
KS = [1.5, 2.0, 3.0, 4.0, 5.0]


def dirty(scale: float) -> Path:
    out = Path(tempfile.mkdtemp(prefix=f"dq-sf{scale:g}-"))
    write(GenConfig(scale=scale, dirty=DirtyConfig.default_dirty()), out)
    return out


def main() -> None:
    folders = {s: dirty(s) for s in SCALES}

    cases = []
    for scale, folder in folders.items():

        def fn(folder=folder):
            rep = run(folder, RULES)
            return {"rows": sum(rep.rows.values()), "checks": len(rep.results)}

        case = measure(fn, label=f"scale {scale:g}", params={"scale": scale}, runs=3)
        case.extra["rows_per_s"] = case.extra["rows"] / case.median_s
        cases.append(case)
        print(f"{case.label}: {case.median_s:.2f} s, {case.extra['rows']:,} rows")
    path = save("runtime_by_scale", cases, notes="30 checks, dirty data, Polars lazy frames.")
    print(plot(path, "median_s", title="Time to run 30 checks, by scale"))

    accuracy = {}
    for scale in (1, 10):
        rep = run(folders[scale], RULES)
        accuracy[f"scale {scale}"] = [
            {"problem": s.problem, "check": s.check, "injected": s.injected,
             "detected": s.detected, "covered": s.covered, "exact": s.exact}
            for s in score_against_truth(rep, folders[scale])
        ]  # fmt: skip
    (RESULTS_DIR / "ground_truth.json").write_text(
        json.dumps({"machine": machine_info(), "results": accuracy}, indent=2), encoding="utf-8"
    )

    conf = outlier_confusion(folders[10], KS)
    rows = [{"k": c.k, "tp": c.tp, "fp": c.fp, "fn": c.fn,
             "precision": c.precision, "recall": c.recall} for c in conf]  # fmt: skip
    (RESULTS_DIR / "outlier_methods.json").write_text(
        json.dumps({"scale": 10, "iqr_log10": rows,
                    "rule_matches_reference": {"precision": 1.0, "recall": 1.0}}, indent=2),
        encoding="utf-8",
    )  # fmt: skip
    plot_outliers(rows)


def plot_outliers(rows: list[dict]) -> None:
    labels = ["rule"] + [f"IQR k={r['k']:g}" for r in rows]
    precision = [1.0] + [r["precision"] for r in rows]
    recall = [1.0] + [r["recall"] for r in rows]
    x = range(len(labels))
    fig, ax = plt.subplots(figsize=(9, 3.8), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    w = 0.38
    ax.bar([i - w / 2 for i in x], precision, w, label="precision", color="#2a78d6", zorder=2)
    ax.bar([i + w / 2 for i in x], recall, w, label="recall", color="#eb6834", zorder=2)
    for i, (p, r) in enumerate(zip(precision, recall, strict=True)):
        ax.text(i - w / 2, p + 0.02, f"{p:.0%}", ha="center", fontsize=7.5, color=INK)
        ax.text(i + w / 2, r + 0.02, f"{r:.0%}", ha="center", fontsize=7.5, color=INK)
    ax.set_xticks(list(x), labels, fontsize=8.5, color=INK)
    ax.set_ylim(0, 1.15)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0%}"))
    ax.tick_params(axis="y", colors=INK_MUTED, labelsize=8)
    ax.tick_params(axis="x", length=0)
    ax.grid(axis="y", color=GRID, linewidth=0.8, zorder=0)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.legend(frameon=False, fontsize=8.5, loc="upper right", ncols=2)
    ax.set_title("Price outliers at scale 10: exact rule vs IQR fences on log10(price)",
                 loc="left", color=INK, fontsize=10, pad=10)  # fmt: skip
    fig.tight_layout()
    out = Path("docs/assets/outlier_methods.png")
    fig.savefig(out, facecolor=SURFACE)
    plt.close(fig)
    print(out)


if __name__ == "__main__":
    main()
