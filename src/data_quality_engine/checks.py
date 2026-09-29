"""Check implementations. Each one counts the rows that break the rule.

Every check accepts ``max_ratio`` (default 0): the share of failing rows that is
still tolerated before the check stops passing.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import polars as pl

from .dataset import PART_COL, Table
from .rules import Check

SAMPLE_SIZE = 5


@dataclass
class CheckResult:
    check: Check
    status: str  # pass, warn, fail
    failed: int
    total: int
    detail: str = ""
    sample: list[Any] = field(default_factory=list)

    @property
    def ratio(self) -> float:
        return self.failed / self.total if self.total else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "check": self.check.name,
            "type": self.check.type,
            "table": self.check.table,
            "column": self.check.column,
            "severity": self.check.severity,
            "status": self.status,
            "failed": self.failed,
            "total": self.total,
            "ratio": round(self.ratio, 6),
            "detail": self.detail,
            "sample": [str(s) for s in self.sample],
        }


def _count(lf: pl.LazyFrame) -> int:
    return lf.select(pl.len()).collect().item()


def _sample(lf: pl.LazyFrame, column: str) -> list[Any]:
    return lf.select(column).unique().head(SAMPLE_SIZE).collect().to_series().to_list()


def _ref(tables: dict[str, Table], spec: str) -> tuple[Table, str]:
    table, _, column = spec.partition(".")
    if table not in tables or not column:
        raise KeyError(f"reference {spec!r} does not point to a loaded table.column")
    return tables[table], column


def check_schema(check: Check, tables: dict[str, Table]) -> tuple[int, int, str, list]:
    table = tables[check.table]
    expected = set(check.params["columns"])
    bad_parts, notes = [], []
    for part, cols in table.part_columns.items():
        missing, extra = sorted(expected - set(cols)), sorted(set(cols) - expected)
        if missing or extra:
            bad_parts.append(part)
            notes.append(f"{part}: missing {missing or '-'}, unexpected {extra or '-'}")
    failed = _count(table.frame.filter(pl.col(PART_COL).is_in(bad_parts))) if bad_parts else 0
    return failed, _count(table.frame), "; ".join(notes), bad_parts[:SAMPLE_SIZE]


def check_not_null(check: Check, tables: dict[str, Table]) -> tuple[int, int, str, list]:
    table = tables[check.table]
    rows = table.rows_with(check.column)
    detail = ""
    if where := check.params.get("where"):
        for col, values in where.items():
            rows = rows.filter(pl.col(col).is_in(values))
        detail = f"only where {where}"
    failed = _count(rows.filter(pl.col(check.column).is_null()))
    return failed, _count(rows), detail, []


def check_unique(check: Check, tables: dict[str, Table]) -> tuple[int, int, str, list]:
    rows = tables[check.table].rows_with(check.column).filter(pl.col(check.column).is_not_null())
    total = _count(rows)
    distinct = rows.select(pl.col(check.column).n_unique()).collect().item()
    dupes = rows.filter(pl.col(check.column).is_duplicated())
    return total - distinct, total, "rows beyond the first per key", _sample(dupes, check.column)


def check_foreign_key(check: Check, tables: dict[str, Table]) -> tuple[int, int, str, list]:
    rows = tables[check.table].rows_with(check.column).filter(pl.col(check.column).is_not_null())
    ref_table, ref_col = _ref(tables, check.params["references"])
    keys = ref_table.frame.select(pl.col(ref_col).alias(check.column)).unique()
    orphans = rows.join(keys, on=check.column, how="anti")
    return (_count(orphans), _count(rows), f"-> {check.params['references']}",
            _sample(orphans, check.column))  # fmt: skip


def check_accepted_values(check: Check, tables: dict[str, Table]) -> tuple[int, int, str, list]:
    rows = tables[check.table].rows_with(check.column).filter(pl.col(check.column).is_not_null())
    bad = rows.filter(~pl.col(check.column).is_in(check.params["values"]))
    return _count(bad), _count(rows), "", _sample(bad, check.column)


def check_range(check: Check, tables: dict[str, Table]) -> tuple[int, int, str, list]:
    rows = tables[check.table].rows_with(check.column).filter(pl.col(check.column).is_not_null())
    cond = pl.lit(False)
    if (lo := check.params.get("min")) is not None:
        cond = cond | (pl.col(check.column) < lo)
    if (hi := check.params.get("max")) is not None:
        cond = cond | (pl.col(check.column) > hi)
    bad = rows.filter(cond)
    return _count(bad), _count(rows), f"[{lo}, {hi}]", _sample(bad, check.column)


def check_matches_reference(check: Check, tables: dict[str, Table]) -> tuple[int, int, str, list]:
    """Value must equal the value in a reference table for the same key
    (e.g. an order line's unit price vs the product's list price)."""
    key = check.params["key"]
    ref_table, ref_col = _ref(tables, check.params["references"])
    ref_key = check.params.get("ref_key", key)
    ref = ref_table.frame.select(pl.col(ref_key).alias(key), pl.col(ref_col).alias("_expected"))
    rows = tables[check.table].rows_with(check.column).join(ref, on=key, how="inner")
    bad = rows.filter(pl.col(check.column) != pl.col("_expected"))
    return (_count(bad), _count(rows), f"== {check.params['references']} by {key}",
            _sample(bad, key))  # fmt: skip


def check_outlier_iqr(check: Check, tables: dict[str, Table]) -> tuple[int, int, str, list]:
    """Tukey fences: outside [Q1 - k*IQR, Q3 + k*IQR], optionally on log10 values."""
    k = float(check.params.get("k", 3.0))
    rows = tables[check.table].rows_with(check.column).filter(pl.col(check.column).is_not_null())
    value = pl.col(check.column).cast(pl.Float64)
    if check.params.get("log"):
        rows = rows.filter(pl.col(check.column) > 0)
        value = value.log10()
    q = rows.select(value.quantile(0.25).alias("q1"), value.quantile(0.75).alias("q3")).collect()
    q1, q3 = q["q1"].item(), q["q3"].item()
    iqr = q3 - q1
    lo, hi = q1 - k * iqr, q3 + k * iqr
    bad = rows.filter((value < lo) | (value > hi))
    scale = "log10 " if check.params.get("log") else ""
    return (_count(bad), _count(rows), f"{scale}fences [{lo:.3f}, {hi:.3f}], k={k}",
            _sample(bad, check.column))  # fmt: skip


RUNNERS: dict[str, Callable[[Check, dict[str, Table]], tuple[int, int, str, list]]] = {
    "schema": check_schema,
    "not_null": check_not_null,
    "unique": check_unique,
    "foreign_key": check_foreign_key,
    "accepted_values": check_accepted_values,
    "range": check_range,
    "matches_reference": check_matches_reference,
    "outlier_iqr": check_outlier_iqr,
}


def run_check(check: Check, tables: dict[str, Table]) -> CheckResult:
    if check.table not in tables:
        return CheckResult(check, "fail", 0, 0, f"table {check.table!r} not found")
    table = tables[check.table]
    if check.column and check.type != "schema" and not table.parts_with(check.column):
        return CheckResult(check, "fail", 0, 0, f"column {check.column!r} not found")
    failed, total, detail, sample = RUNNERS[check.type](check, tables)
    tolerated = total and failed / total <= float(check.params.get("max_ratio", 0))
    broken = "fail" if check.severity == "error" else "warn"
    status = "pass" if failed == 0 or tolerated else broken
    return CheckResult(check, status, failed, total, detail, sample)
