"""Render a Report for the terminal, as Markdown, or as JSON."""

from __future__ import annotations

import json
from collections import Counter

from .engine import Report

BAR_WIDTH = 20
ICON = {"pass": "PASS", "warn": "WARN", "fail": "FAIL"}


def score_bar(score: float) -> str:
    filled = round(score / 100 * BAR_WIDTH)
    return "█" * filled + "░" * (BAR_WIDTH - filled)


def summary_lines(report: Report) -> list[str]:
    counts = Counter(r.status for r in report.results)
    lines = [
        "DATA QUALITY SCORE",
        "",
        f"{score_bar(report.score)} {report.score:.0f}%",
        "",
        f"{'Rows analyzed':<22}{sum(report.rows.values()):>14,}",
        f"{'Tables / columns':<22}{len(report.rows):>7} / {sum(report.columns.values()):<5}",
        f"{'Checks':<22}{len(report.results):>14}  "
        f"({counts['pass']} pass, {counts['warn']} warn, {counts['fail']} fail)",
        f"{'Null violations':<22}{report.failed_rows('not_null'):>14,}",
        f"{'Duplicate rows':<22}{report.failed_rows('unique'):>14,}",
        f"{'Orphan references':<22}{report.failed_rows('foreign_key'):>14,}",
        f"{'Schema drift rows':<22}{report.failed_rows('schema'):>14,}",
        f"{'Value mismatches':<22}{report.failed_rows('matches_reference'):>14,}",
        f"{'Statistical outliers':<22}{report.failed_rows('outlier_iqr'):>14,}",
        f"{'Elapsed':<22}{report.elapsed_s:>13.2f}s",
        "",
        f"STATUS: {report.status}",
    ]
    return lines


def to_text(report: Report, verbose: bool = True) -> str:
    lines = summary_lines(report)
    if verbose:
        lines += ["", f"{'status':<6} {'check':<48} {'failed':>10} {'of':>12}"]
        for r in report.results:
            lines.append(
                f"{ICON[r.status]:<6} {r.check.name:<48} {r.failed:>10,} {r.total:>12,}"
                + (f"  {r.detail}" if r.detail and r.status != "pass" else "")
            )
    return "\n".join(lines)


def to_markdown(report: Report) -> str:
    out = [
        f"# Data quality report: `{report.dataset}`",
        "",
        "```",
        *summary_lines(report),
        "```",
        "",
        "| Status | Check | Severity | Failed | Of | Ratio | Detail | Sample |",
        "|---|---|---|---:|---:|---:|---|---|",
    ]
    for r in report.results:
        sample = ", ".join(f"`{s}`" for s in r.sample)
        out.append(
            f"| {ICON[r.status]} | `{r.check.name}` | {r.check.severity} | {r.failed:,} | "
            f"{r.total:,} | {r.ratio:.4%} | {r.detail} | {sample} |"
        )
    return "\n".join(out) + "\n"


def to_json(report: Report) -> str:
    return json.dumps(report.to_dict(), indent=2, ensure_ascii=False)
