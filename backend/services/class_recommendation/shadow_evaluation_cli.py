"""CLI for recommendation shadow-vs-feedback evaluation reports."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .shadow_evaluation import build_shadow_evaluation_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate persisted shadow scores against explicit user feedback."
    )
    parser.add_argument(
        "--include-fixture-feedback",
        action="store_true",
        help="Smoke-test only. Include synthetic acceptance namespace feedback.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional JSON file to receive the report in addition to stdout.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = build_shadow_evaluation_report(
        include_fixture_feedback=args.include_fixture_feedback,
    )
    rendered = json.dumps(report, indent=2, sort_keys=True, default=str)
    print(rendered)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
