"""CLI for read-only offline recommendation-feedback learning reports."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .learning import build_learning_report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fit offline Logistic Regression baselines from recommendation feedback."
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional JSON file to receive the report in addition to stdout.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_learning_report()
    rendered = json.dumps(report, indent=2, sort_keys=True)
    print(rendered)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
