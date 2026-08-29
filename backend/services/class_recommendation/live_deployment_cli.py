"""CLI for gated recommendation live ranking deployment and rollback."""

from __future__ import annotations

import argparse
import json

from .live_deployment import LivePromotionGateConfig, recommendation_live_deployments


def _gate_args(parser: argparse.ArgumentParser) -> None:
    defaults = LivePromotionGateConfig()
    parser.add_argument("--min-samples", type=int, default=defaults.min_samples)
    parser.add_argument("--min-positive", type=int, default=defaults.min_positive)
    parser.add_argument("--min-negative", type=int, default=defaults.min_negative)
    parser.add_argument(
        "--min-unique-candidates", type=int, default=defaults.min_unique_candidates
    )
    parser.add_argument(
        "--min-balanced-accuracy", type=float, default=defaults.min_balanced_accuracy
    )
    parser.add_argument("--min-roc-auc", type=float, default=defaults.min_roc_auc)
    parser.add_argument(
        "--min-pairwise-comparisons",
        type=int,
        default=defaults.min_pairwise_comparisons,
    )
    parser.add_argument(
        "--min-pairwise-accuracy-delta",
        type=float,
        default=defaults.min_pairwise_accuracy_delta,
    )


def _gate_config(args: argparse.Namespace) -> LivePromotionGateConfig:
    return LivePromotionGateConfig(
        min_samples=args.min_samples,
        min_positive=args.min_positive,
        min_negative=args.min_negative,
        min_unique_candidates=args.min_unique_candidates,
        min_balanced_accuracy=args.min_balanced_accuracy,
        min_roc_auc=args.min_roc_auc,
        min_pairwise_comparisons=args.min_pairwise_comparisons,
        min_pairwise_accuracy_delta=args.min_pairwise_accuracy_delta,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manage gated learned ranking for Recommended Classes."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="Evaluate one model against the live gate.")
    check.add_argument("model_id")
    _gate_args(check)

    activate = sub.add_parser(
        "activate",
        help="Activate a gate-passing candidate-quality model for live ordering.",
    )
    activate.add_argument("model_id")
    activate.add_argument("--reason", required=True)
    _gate_args(activate)

    sub.add_parser("status", help="Show the current live deployment.")

    rollback = sub.add_parser(
        "rollback",
        help="Immediately restore baseline HDBSCAN/centroid ordering.",
    )
    rollback.add_argument("--reason", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    registry = recommendation_live_deployments
    try:
        if args.command == "check":
            result = registry.check(
                model_id=args.model_id,
                config=_gate_config(args),
            )
        elif args.command == "activate":
            result = registry.activate(
                model_id=args.model_id,
                reason=args.reason,
                config=_gate_config(args),
            )
        elif args.command == "status":
            result = registry.status()
        elif args.command == "rollback":
            result = registry.rollback(reason=args.reason)
        else:  # pragma: no cover
            raise ValueError(f"Unknown command: {args.command}")
    except (LookupError, ValueError) as exc:
        print(json.dumps({"status": "error", "detail": str(exc)}, indent=2))
        return 2

    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
