import json
from pathlib import Path

import polars as pl
import pytest
from shopflow_datagen import DirtyConfig, GenConfig, write

from data_quality_engine import report as render
from data_quality_engine.checks import run_check
from data_quality_engine.cli import main
from data_quality_engine.dataset import load
from data_quality_engine.engine import run
from data_quality_engine.evaluate import outlier_confusion, score_against_truth
from data_quality_engine.rules import Check, RuleError, parse
from data_quality_engine.rules import load as load_rules

RULES = Path(__file__).resolve().parent.parent / "rules" / "shopflow.yml"


def _write(folder: Path, table: str, *frames: pl.DataFrame) -> None:
    (folder / table).mkdir(parents=True, exist_ok=True)
    for i, df in enumerate(frames):
        df.write_parquet(folder / table / f"part-{i:05d}.parquet")


@pytest.fixture
def tiny(tmp_path) -> Path:
    _write(tmp_path, "products", pl.DataFrame({"product_id": [1, 2, 3], "price": [100, 200, 300]}))
    _write(
        tmp_path,
        "items",
        pl.DataFrame(
            {
                "item_id": [1, 2, 2, 4, 5],
                "product_id": [1, 2, 9, 3, None],
                "price": [100, 200, 999, 300, 100],
                "status": ["ok", "ok", "bad", None, "ok"],
                "qty": [1, 0, 3, 2, 50],
            }
        ),
        # a later file where a column was renamed: schema drift
        pl.DataFrame(
            {"item_id": [6], "product_id": [1], "unit_price": [100], "status": ["ok"], "qty": [1]}
        ),  # fmt: skip
    )
    return tmp_path


def _result(folder, check):
    return run_check(check, load(folder))


def test_parse_rejects_malformed_rules():
    with pytest.raises(RuleError, match="tables"):
        parse({})
    with pytest.raises(RuleError, match="type"):
        parse({"tables": {"t": {"checks": [{"column": "a"}]}}})
    with pytest.raises(RuleError, match="unknown"):
        parse({"tables": {"t": {"checks": [{"type": "magic", "column": "a"}]}}})
    with pytest.raises(RuleError, match="severity"):
        parse({"tables": {"t": {"checks": [{"type": "unique", "column": "a", "severity": "x"}]}}})
    with pytest.raises(RuleError, match="column"):
        parse({"tables": {"t": {"checks": [{"type": "unique"}]}}})


def test_shopflow_rules_load():
    rules = load_rules(RULES)
    assert len(rules.checks) == 30
    assert {c.type for c in rules.checks} >= {"schema", "foreign_key", "matches_reference"}


def test_schema_drift_flags_the_rows_of_the_drifted_file(tiny):
    expected = ["item_id", "product_id", "price", "status", "qty"]
    r = _result(tiny, Check("schema", "items", params={"columns": expected}))
    assert (r.failed, r.total, r.status) == (1, 6, "fail")
    assert "unexpected ['unit_price']" in r.detail and "missing ['price']" in r.detail


def test_not_null_ignores_files_without_the_column_and_honors_where(tiny):
    assert _result(tiny, Check("not_null", "items", "price")).failed == 0  # drifted file excluded
    r = _result(tiny, Check("not_null", "items", "status"))
    assert (r.failed, r.total) == (1, 6)
    r = _result(tiny, Check("not_null", "items", "status", params={"where": {"qty": [2]}}))
    assert (r.failed, r.total) == (1, 1)


def test_unique_counts_rows_beyond_the_first(tiny):
    r = _result(tiny, Check("unique", "items", "item_id"))
    assert (r.failed, r.sample) == (1, [2])


def test_foreign_key_finds_orphans_and_skips_nulls(tiny):
    r = _result(tiny, Check("foreign_key", "items", "product_id",
                            params={"references": "products.product_id"}))  # fmt: skip
    assert (r.failed, r.total, r.sample) == (1, 5, [9])


def test_accepted_values_and_range(tiny):
    r = _result(tiny, Check("accepted_values", "items", "status", params={"values": ["ok"]}))
    assert r.failed == 1
    r = _result(tiny, Check("range", "items", "qty", params={"min": 1, "max": 10}))
    assert r.failed == 2 and sorted(r.sample) == [0, 50]


def test_matches_reference_compares_by_key(tiny):
    params = {"key": "product_id", "references": "products.price"}
    r = _result(tiny, Check("matches_reference", "items", "price", params=params))
    # product 9 is an orphan (not joinable) and product None too: only 3 comparable rows
    assert (r.failed, r.total) == (0, 3)


def test_severity_and_tolerance(tiny):
    warn = _result(tiny, Check("unique", "items", "item_id", severity="warn"))
    assert warn.status == "warn"
    tolerated = _result(tiny, Check("unique", "items", "item_id", params={"max_ratio": 0.5}))
    assert tolerated.status == "pass"
    missing = _result(tiny, Check("unique", "items", "nope"))
    assert missing.status == "fail" and "not found" in missing.detail


def test_outlier_iqr_flags_extremes(tmp_path):
    _write(tmp_path, "t", pl.DataFrame({"v": [10, 11, 12, 13, 12, 11, 10, 1000]}))
    r = _result(tmp_path, Check("outlier_iqr", "t", "v", params={"k": 3}))
    assert (r.failed, r.sample) == (1, [1000])


@pytest.fixture(scope="module")
def shopflow(tmp_path_factory):
    clean = tmp_path_factory.mktemp("clean")
    write(GenConfig(scale=0.05, chunk_size=2_000), clean)
    dirty = tmp_path_factory.mktemp("dirty")
    write(GenConfig(scale=0.05, chunk_size=2_000, dirty=DirtyConfig.default_dirty()), dirty)
    return clean, dirty


def test_clean_data_passes_every_error_check(shopflow):
    rep = run(shopflow[0], load_rules(RULES))
    assert rep.status in {"PASS", "WARNING"}
    assert all(r.status != "fail" for r in rep.results)


def test_every_injected_problem_is_found_exactly(shopflow):
    dirty = shopflow[1]
    rep = run(dirty, load_rules(RULES))
    assert rep.status == "FAIL"
    scores = score_against_truth(rep, dirty)
    covered = [s for s in scores if s.covered]
    assert len(covered) == 6
    assert all(s.exact for s in covered), [(s.problem, s.injected, s.detected) for s in covered]


def test_rule_beats_statistics_on_price_outliers(shopflow):
    loose, strict = outlier_confusion(shopflow[1], [1.5, 4.0])
    assert loose.recall == 1.0 and loose.precision < 0.1  # catches all, mostly false alarms
    assert strict.precision > loose.precision and strict.recall < 1.0


def test_score_weights_errors_above_warnings(shopflow):
    rep = run(shopflow[1], load_rules(RULES))
    assert 0 < rep.score < 100
    assert rep.failed_rows("unique") > 0


def test_renderers(shopflow):
    rep = run(shopflow[1], load_rules(RULES))
    text = render.to_text(rep)
    assert "DATA QUALITY SCORE" in text and "STATUS: FAIL" in text and "█" in text
    md = render.to_markdown(rep)
    assert md.count("\n| ") >= len(rep.results)
    assert json.loads(render.to_json(rep))["status"] == "FAIL"


def test_cli_exit_codes(shopflow, tmp_path, capsys):
    clean, dirty = shopflow
    assert main(["check", str(clean), "--rules", str(RULES), "--quiet"]) == 0
    out_json, out_md = tmp_path / "r.json", tmp_path / "r.md"
    assert main(["check", str(dirty), "--rules", str(RULES), "--json", str(out_json),
                 "--md", str(out_md)]) == 1  # fmt: skip
    assert json.loads(out_json.read_text())["status"] == "FAIL" and out_md.exists()
    assert main(["evaluate", str(dirty), "--rules", str(RULES)]) == 0
    assert main(["evaluate", str(clean), "--rules", str(RULES)]) == 2
    assert "outside contract" in capsys.readouterr().out
