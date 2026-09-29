"""Score the engine against the problems shopflow-datagen injected on purpose.

shopflow-datagen's ``_manifest.json`` records exactly how many rows of each
kind of problem it injected. Here each problem is matched to the check that
should catch it, and detected vs injected is compared.

For price outliers there is also a row-level comparison of two approaches:
the exact rule (unit price must equal the product's list price) and Tukey's
statistical fences. In clean shopflow data every line is sold at list price
(an invariant tested in shopflow-datagen), so a line whose price differs from
the list price is an injected outlier. That gives row-level ground truth to
compute precision and recall of the statistical method.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import polars as pl

from .dataset import load
from .engine import Report

# injected problem in the manifest -> the check that should find it
PROBLEM_TO_CHECK = {
    "customers.email.null": "not_null(customers.email)",
    "orders.channel.null": "not_null(orders.channel)",
    "orders.duplicate_rows": "unique(orders.order_id)",
    "order_items.orphan_product_id": "foreign_key(order_items.product_id)",
    "order_items.price_outlier": "matches_reference(order_items.unit_price_cents)",
    "orders.schema_drift_rows": "schema(orders)",
    # The drifted file renamed channel to sales_channel, a column outside the
    # contract: no null rule applies to it, and its rows are flagged by schema().
    "orders.sales_channel.null": None,
}


@dataclass
class ProblemScore:
    problem: str
    check: str
    injected: int
    detected: int

    @property
    def covered(self) -> bool:
        return self.check != "-"

    @property
    def exact(self) -> bool:
        return not self.covered or self.injected == self.detected


def ground_truth(folder: Path) -> dict[str, int]:
    manifest = json.loads((folder / "_manifest.json").read_text(encoding="utf-8"))
    return manifest.get("dirty_ground_truth", {})


def score_against_truth(report: Report, folder: Path) -> list[ProblemScore]:
    truth = ground_truth(folder)
    by_name = {r.check.name: r for r in report.results}
    scores = []
    for problem, injected in truth.items():
        check = PROBLEM_TO_CHECK.get(problem)
        result = by_name.get(check) if check else None
        scores.append(ProblemScore(problem, check or "-", injected,
                                   result.failed if result else 0))  # fmt: skip
    return scores


@dataclass
class Confusion:
    k: float
    tp: int
    fp: int
    fn: int

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else 0.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else 0.0


def outlier_confusion(folder: Path, ks: list[float], log: bool = True) -> list[Confusion]:
    """Precision and recall of IQR fences on order_items.unit_price_cents, per k."""
    tables = load(folder)
    items = tables["order_items"].frame
    prices = tables["products"].frame.select("product_id", pl.col("price_cents").alias("_list"))
    labeled = (
        items.join(prices, on="product_id", how="inner")
        .with_columns((pl.col("unit_price_cents") != pl.col("_list")).alias("_truth"))
        .select("unit_price_cents", "_truth")
        .collect()
    )
    value = labeled["unit_price_cents"].cast(pl.Float64)
    if log:
        value = value.log10()
    q1, q3 = value.quantile(0.25), value.quantile(0.75)
    truth = labeled["_truth"]
    out = []
    for k in ks:
        iqr = q3 - q1
        pred = (value < q1 - k * iqr) | (value > q3 + k * iqr)
        tp = int((pred & truth).sum())
        out.append(Confusion(k, tp, int((pred & ~truth).sum()), int((~pred & truth).sum())))
    return out
