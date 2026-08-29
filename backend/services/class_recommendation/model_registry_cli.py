"""CLI for versioned offline recommendation-learning model artifacts."""

from __future__ import annotations

import argparse
import json

from .model_registry import EvaluationGateConfig, recommendation_model_registry


def _gate_args(parser: argparse.ArgumentParser) -> None:
    defaults = EvaluationGateConfig()
    parser.add_argument("--min-samples", type=int, default=defaults.min_samples)
    parser.add_argument("--min-positive", type=int, default=defaults.min_positive)
    parser.add_argument("--min-negative", type=int, default=defaults.min_negative)
    parser.add_argument(
        "--min-evaluation-groups", type=int, default=defaults.min_evaluation_groups
    )
    parser.add_argument(
        "--min-balanced-accuracy", type=float, default=defaults.min_balanced_accuracy
    )
    parser.add_argument("--min-roc-auc", type=float, default=defaults.min_roc_auc)


def _gate_config(args: argparse.Namespace) -> EvaluationGateConfig:
    return EvaluationGateConfig(
        min_samples=args.min_samples,
        min_positive=args.min_positive,
        min_negative=args.min_negative,
        min_evaluation_groups=args.min_evaluation_groups,
        min_balanced_accuracy=args.min_balanced_accuracy,
        min_roc_auc=args.min_roc_auc,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manage offline recommendation-learning model artifacts."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    register = sub.add_parser(
        "register",
        help="Train reproducible artifacts from current feedback and register candidates.",
    )
    register.add_argument(
        "--include-fixture-feedback",
        action="store_true",
        help="Smoke-test only. Fixture-inclusive models cannot pass the default source gate.",
    )
    _gate_args(register)

    list_cmd = sub.add_parser("list", help="List registered model versions.")
    list_cmd.add_argument(
        "--objective", choices=("membership", "candidate_quality"), default=None
    )

    show = sub.add_parser("show", help="Show one model plus its evaluations.")
    show.add_argument("model_id")

    approve = sub.add_parser(
        "approve-offline",
        help="Approve a gate-passing model for offline/shadow experimentation only.",
    )
    approve.add_argument("model_id")
    approve.add_argument("evaluation_id")
    approve.add_argument("--reason", required=True)

    retire = sub.add_parser("retire", help="Retire a registered model version.")
    retire.add_argument("model_id")
    retire.add_argument("--reason", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    registry = recommendation_model_registry

    try:
        if args.command == "register":
            result = registry.register_from_feedback(
                include_fixture_feedback=args.include_fixture_feedback,
                gate_config=_gate_config(args),
            )
        elif args.command == "list":
            result = registry.list_models(args.objective)
        elif args.command == "show":
            model = registry.get_model(args.model_id)
            if model is None:
                raise LookupError("Recommendation model was not found")
            result = {
                "model": model,
                "evaluations": registry.list_evaluations(args.model_id),
                "runtime_effect": "none",
            }
        elif args.command == "approve-offline":
            result = registry.approve_offline(
                model_id=args.model_id,
                evaluation_id=args.evaluation_id,
                reason=args.reason,
            )
        elif args.command == "retire":
            result = registry.retire(model_id=args.model_id, reason=args.reason)
        else:  # pragma: no cover - argparse prevents this
            raise ValueError(f"Unknown command: {args.command}")
    except (LookupError, ValueError) as exc:
        print(json.dumps({"status": "error", "detail": str(exc)}, indent=2))
        return 2

    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
