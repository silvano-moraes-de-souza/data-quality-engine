"""dq-engine command line.

    dq-engine check data/sf1 --rules rules/shopflow.yml
    dq-engine check data/sf1 --rules rules/shopflow.yml --json report.json --md report.md
    dq-engine evaluate data/sf1-dirty --rules rules/shopflow.yml

`check` exits with 1 when an error-level check fails, so it can gate a pipeline or CI.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import report as render
from .engine import run
from .evaluate import outlier_confusion, score_against_truth
from .rules import load as load_rules


def cmd_check(args: argparse.Namespace) -> int:
    rep = run(args.folder, load_rules(args.rules))
    print(render.to_text(rep, verbose=not args.quiet))
    if args.json:
        args.json.write_text(render.to_json(rep), encoding="utf-8")
    if args.md:
        args.md.write_text(render.to_markdown(rep), encoding="utf-8")
    return 1 if rep.status == "FAIL" else 0


def cmd_evaluate(args: argparse.Namespace) -> int:
    rep = run(args.folder, load_rules(args.rules))
    scores = score_against_truth(rep, args.folder)
    if not scores:
        print("no dirty_ground_truth in _manifest.json (generate with --dirty)", file=sys.stderr)
        return 2
    print(f"{'problem':<32} {'check':<48} {'injected':>9} {'detected':>9}")
    for s in scores:
        mark = "outside contract" if not s.covered else ("exact" if s.exact else "MISMATCH")
        print(f"{s.problem:<32} {s.check:<48} {s.injected:>9,} {s.detected:>9,}  {mark}")
    print("\nIQR fences on log10(unit_price_cents) vs row-level truth:")
    print(f"{'k':>5} {'TP':>7} {'FP':>7} {'FN':>7} {'precision':>10} {'recall':>8}")
    for c in outlier_confusion(args.folder, [1.5, 2.0, 3.0, 4.0]):
        print(f"{c.k:>5} {c.tp:>7,} {c.fp:>7,} {c.fn:>7,} {c.precision:>10.1%} {c.recall:>8.1%}")
    return 0 if all(s.exact for s in scores) else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="dq-engine", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = p.add_subparsers(dest="command", required=True)
    c = sub.add_parser("check", help="run the rules and print the report")
    c.add_argument("folder", type=Path)
    c.add_argument("--rules", type=Path, required=True)
    c.add_argument("--json", type=Path)
    c.add_argument("--md", type=Path)
    c.add_argument("--quiet", action="store_true", help="summary only")
    c.set_defaults(func=cmd_check)
    e = sub.add_parser("evaluate", help="compare findings with injected ground truth")
    e.add_argument("folder", type=Path)
    e.add_argument("--rules", type=Path, required=True)
    e.set_defaults(func=cmd_evaluate)
    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
