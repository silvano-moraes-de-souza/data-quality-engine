"""Rule files: YAML describing, per table, the expected columns and the checks.

tables:
  orders:
    columns: [order_id, customer_id, ordered_at, status, ...]
    checks:
      - {type: unique, column: order_id}
      - {type: not_null, column: channel, severity: warn}
      - {type: foreign_key, column: customer_id, references: customers.customer_id}
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

CHECK_TYPES = {
    "schema",
    "not_null",
    "unique",
    "foreign_key",
    "accepted_values",
    "range",
    "matches_reference",
    "outlier_iqr",
}
SEVERITIES = {"error", "warn"}


class RuleError(ValueError):
    """The rule file is malformed."""


@dataclass(frozen=True)
class Check:
    type: str
    table: str
    column: str | None = None
    severity: str = "error"
    params: dict[str, Any] = field(default_factory=dict)

    @property
    def name(self) -> str:
        target = f"{self.table}.{self.column}" if self.column else self.table
        return f"{self.type}({target})"


@dataclass(frozen=True)
class RuleSet:
    checks: list[Check]
    source: str = ""


def parse(data: dict) -> RuleSet:
    if not isinstance(data, dict) or not isinstance(data.get("tables"), dict):
        raise RuleError("rule file must have a 'tables' mapping")
    checks: list[Check] = []
    for table, raw_spec in data["tables"].items():
        spec = raw_spec or {}
        if "columns" in spec:
            checks.append(Check("schema", table, params={"columns": list(spec["columns"])}))
        for raw in spec.get("checks", []):
            if not isinstance(raw, dict) or "type" not in raw:
                raise RuleError(f"{table}: every check needs a 'type', got {raw!r}")
            item = dict(raw)
            kind = item.pop("type")
            if kind not in CHECK_TYPES - {"schema"}:
                raise RuleError(f"{table}: unknown check type {kind!r}")
            severity = item.pop("severity", "error")
            if severity not in SEVERITIES:
                raise RuleError(f"{table}: severity must be one of {sorted(SEVERITIES)}")
            column = item.pop("column", None)
            if column is None:
                raise RuleError(f"{table}: check {kind!r} needs a 'column'")
            checks.append(Check(kind, table, column, severity, item))
    return RuleSet(checks)


def load(path: Path) -> RuleSet:
    rules = parse(yaml.safe_load(path.read_text(encoding="utf-8")))
    return RuleSet(rules.checks, source=str(path))
