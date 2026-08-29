"""Build and evaluate recommendation-feedback learning baselines.

The command is read-only with respect to recommendation state. By default it connects
using the host process POSTGRES_DSN. Use ``--docker`` for the normal Compose setup,
where PostgreSQL is intentionally not published to the host and is reachable from the
backend container as ``postgres:5432``.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from services.class_recommendation.learning import build_learning_report  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fit offline Logistic Regression baselines from recommendation feedback."
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional host JSON file to receive the report in addition to stdout.",
    )
    parser.add_argument(
        "--docker",
        action="store_true",
        help="Run the report inside the Compose backend container so it can reach PostgreSQL.",
    )
    return parser.parse_args()


def _write_output(path: Path | None, rendered: str) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered.rstrip() + "\n", encoding="utf-8")


def _run_docker(output: Path | None) -> int:
    command = [
        "docker",
        "compose",
        "exec",
        "-T",
        "backend",
        "python",
        "-m",
        "services.class_recommendation.learning_cli",
    ]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.stdout:
        print(completed.stdout, end="" if completed.stdout.endswith("\n") else "\n")
    if completed.stderr:
        print(completed.stderr, file=sys.stderr, end="" if completed.stderr.endswith("\n") else "\n")
    if completed.returncode == 0:
        _write_output(output, completed.stdout)
    else:
        print(
            "Docker training requires a running backend built from the current branch. "
            "Run: docker compose up -d --build",
            file=sys.stderr,
        )
    return completed.returncode


def main() -> int:
    args = parse_args()
    if args.docker:
        return _run_docker(args.output)

    report = build_learning_report()
    rendered = json.dumps(report, indent=2, sort_keys=True)
    print(rendered)
    _write_output(args.output, rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
