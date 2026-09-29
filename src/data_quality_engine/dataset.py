"""Read a folder of tables (``<table>/part-*.parquet`` or ``.csv``) as Polars frames.

Part files of the same table may have different columns (schema drift). They
are concatenated diagonally, with a ``_part`` column recording the source file,
so a check can tell "this value is null" apart from "this file has no such column".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import polars as pl

PART_COL = "_part"


@dataclass
class Table:
    name: str
    frame: pl.LazyFrame
    part_columns: dict[str, list[str]] = field(default_factory=dict)  # part file -> columns

    def parts_with(self, column: str) -> list[str]:
        return [p for p, cols in self.part_columns.items() if column in cols]

    def rows_with(self, column: str) -> pl.LazyFrame:
        """Rows coming from part files that actually have ``column``."""
        return self.frame.filter(pl.col(PART_COL).is_in(self.parts_with(column)))


def _scan(path: Path) -> pl.LazyFrame:
    if path.suffix == ".parquet":
        return pl.scan_parquet(path)
    return pl.scan_csv(path, try_parse_dates=True)


def load(folder: Path) -> dict[str, Table]:
    tables: dict[str, Table] = {}
    for sub in sorted(p for p in folder.iterdir() if p.is_dir()):
        parts = sorted([*sub.glob("part-*.parquet"), *sub.glob("part-*.csv")])
        if not parts:
            continue
        frames, part_columns = [], {}
        for part in parts:
            lf = _scan(part)
            part_columns[part.name] = lf.collect_schema().names()
            frames.append(lf.with_columns(pl.lit(part.name).alias(PART_COL)))
        frame = pl.concat(frames, how="diagonal_relaxed")
        tables[sub.name] = Table(sub.name, frame, part_columns)
    if not tables:
        raise FileNotFoundError(f"no table folders with part files under {folder}")
    return tables
