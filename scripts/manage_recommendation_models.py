"""Host/Docker wrapper for the recommendation model registry CLI."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from services.class_recommendation.model_registry_cli import main as registry_main  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--docker", action="store_true")
    known, remaining = parser.parse_known_args(raw)

    if not known.docker:
        return registry_main(remaining)

    command = [
        "docker",
        "compose",
        "exec",
        "-T",
        "backend",
        "python",
        "-m",
        "services.class_recommendation.model_registry_cli",
        *remaining,
    ]
    completed = subprocess.run(command, cwd=ROOT, check=False)
    if completed.returncode != 0:
        print(
            "Docker model-registry commands require a running backend built from the current branch. "
            "Run: docker compose up -d --build",
            file=sys.stderr,
        )
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
