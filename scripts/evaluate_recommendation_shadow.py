"""Host/Docker wrapper for recommendation shadow evaluation reports."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from services.class_recommendation.shadow_evaluation_cli import (  # noqa: E402
    main as evaluation_main,
)


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--docker", action="store_true")
    known, remaining = parser.parse_known_args(raw)

    if not known.docker:
        return evaluation_main(remaining)

    command = [
        "docker",
        "compose",
        "exec",
        "-T",
        "backend",
        "python",
        "-m",
        "services.class_recommendation.shadow_evaluation_cli",
        *remaining,
    ]
    completed = subprocess.run(command, cwd=ROOT, check=False)
    if completed.returncode != 0:
        print(
            "Docker shadow evaluation requires a running backend built from the current branch. "
            "Run: docker compose up -d --build",
            file=sys.stderr,
        )
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
