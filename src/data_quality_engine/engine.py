"""Run a rule set over a dataset and summarize it as a quality report."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .checks import CheckResult, run_check
from .dataset import load
from .rules import RuleSet

# An error-level check weighs more than a warning in the score.
WEIGHTS = {"error": 3, "warn": 1}


@dataclass
class Report:
    dataset: str
    rules: str
    results: list[CheckResult]
    rows: dict[str, int]
    columns: dict[str, int]
    elapsed_s: float
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))

    @property
    def score(self) -> float:
        """Weighted share of checks that pass, 0 to 100."""
        total = sum(WEIGHTS[r.check.severity] for r in self.results)
        passed = sum(WEIGHTS[r.check.severity] for r in self.results if r.status == "pass")
        return 100.0 * passed / total if total else 100.0

    @property
    def status(self) -> str:
        statuses = {r.status for r in self.results}
        if "fail" in statuses:
            return "FAIL"
        if "warn" in statuses:
            return "WARNING"
        return "PASS"

    def failed_rows(self, check_type: str) -> int:
        return sum(r.failed for r in self.results if r.check.type == check_type)

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset": self.dataset,
            "rules": self.rules,
            "created_at": self.created_at,
            "status": self.status,
            "score": round(self.score, 2),
            "elapsed_s": round(self.elapsed_s, 3),
            "rows": self.rows,
            "columns": self.columns,
            "results": [r.to_dict() for r in self.results],
        }


def run(folder: Path, rules: RuleSet) -> Report:
    t0 = time.perf_counter()
    tables = load(folder)
    results = [run_check(c, tables) for c in rules.checks]
    rows = {n: t.frame.select("_part").collect().height for n, t in tables.items()}
    columns = {
        n: len({c for cols in t.part_columns.values() for c in cols}) for n, t in tables.items()
    }
    return Report(str(folder), rules.source, results, rows, columns, time.perf_counter() - t0)
