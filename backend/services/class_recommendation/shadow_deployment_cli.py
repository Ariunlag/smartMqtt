"""CLI for explicit recommendation shadow deployment lifecycle."""

from __future__ import annotations

import argparse
import json

from .shadow_deployment import OBJECTIVES, recommendation_shadow_deployments


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Activate/deactivate offline-approved recommendation models in shadow mode."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="List current shadow deployments.")

    activate = sub.add_parser(
        "activate",
        help="Activate one OFFLINE_APPROVED model for observational shadow scoring.",
    )
    activate.add_argument("model_id")
    activate.add_argument("--reason", required=True)

    deactivate = sub.add_parser(
        "deactivate",
        help="Deactivate shadow scoring for one learning objective.",
    )
    deactivate.add_argument("objective", choices=tuple(sorted(OBJECTIVES)))
    deactivate.add_argument("--reason", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    registry = recommendation_shadow_deployments
    try:
        if args.command == "status":
            result = registry.status()
        elif args.command == "activate":
            result = registry.activate(model_id=args.model_id, reason=args.reason)
        elif args.command == "deactivate":
            result = registry.deactivate(objective=args.objective, reason=args.reason)
        else:  # pragma: no cover - argparse prevents this
            raise ValueError(f"Unknown command: {args.command}")
    except (LookupError, ValueError) as exc:
        print(json.dumps({"status": "error", "detail": str(exc)}, indent=2))
        return 2

    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
