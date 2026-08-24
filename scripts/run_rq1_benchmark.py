"""Command-line entry point for the isolated SmartMQTT RQ1 benchmark."""

from __future__ import annotations

import argparse
import hashlib
import math
import sys
import time
from dataclasses import replace
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from config import config
from services.embedding.base_model import BaseEmbeddingModel
from services.semantic.evaluation.rq1_benchmark import (
    RQ1BenchmarkRunner,
    RQ1Condition,
    RQ1DecisionConfig,
    write_rq1_artifacts,
)
from services.semantic.evaluation.rq1_dataset import (
    RQ1Split,
    load_rq1_dataset,
)
from services.semantic.evaluation.rq1_representations import (
    IndependentFusion,
    RQ1RepresentationConfig,
    RQ1Variant,
)


class DeterministicHashEmbeddingModel(BaseEmbeddingModel):
    """Dependency-free evaluation model for tests and smoke validation only."""

    def __init__(self, dimension: int = 32):
        if dimension < 2:
            raise ValueError("hash embedding dimension must be at least 2")
        self.dimension = dimension

    def encode(self, texts):
        vectors = []
        for text in texts:
            values = [0.0] * self.dimension
            tokens = text.lower().split()
            for token in tokens or ["<empty>"]:
                digest = hashlib.sha256(token.encode("utf-8")).digest()
                index = int.from_bytes(digest[:4], "big") % self.dimension
                values[index] += -1.0 if digest[4] & 1 else 1.0
            norm = math.sqrt(sum(value * value for value in values)) or 1.0
            vectors.append([value / norm for value in values])
        return vectors


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the SmartMQTT RQ1 benchmark")
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--variants",
        default=",".join(
            item.value for item in RQ1Variant if item is not RQ1Variant.NUMERIC_BUCKET
        ),
        help="Comma-separated RQ1 variant names",
    )
    parser.add_argument("--split", choices=("VALIDATION", "TEST"), default="VALIDATION")
    parser.add_argument(
        "--embedding-backend",
        choices=("sentence-transformer", "deterministic-hash"),
        default="sentence-transformer",
    )
    parser.add_argument("--model-name", default=config.EMBEDDING_MODEL)
    parser.add_argument("--device", default=config.EMBEDDING_DEVICE)
    parser.add_argument("--hash-dimension", type=int, default=32)
    parser.add_argument(
        "--independent-fusion",
        choices=tuple(item.value for item in IndependentFusion),
        default=IndependentFusion.MEAN.value,
    )
    parser.add_argument("--key-weight", type=float, default=0.5)
    parser.add_argument("--numeric-buckets", default="")
    parser.add_argument("--known-min-similarity", type=float, default=0.55)
    parser.add_argument("--known-min-margin", type=float, default=0.0)
    parser.add_argument("--unknown-max-similarity", type=float, default=0.15)
    parser.add_argument("--bootstrap-repetitions", type=int, default=200)
    parser.add_argument("--diagnostics", action="store_true")
    parser.add_argument("--scale-sizes", default="")
    parser.add_argument("--include-multiview", action="store_true")
    parser.add_argument(
        "--static-weights",
        default="",
        help=(
            "Calibration-derived weights as VARIANT=WEIGHT pairs; adds a "
            "STATIC_WEIGHTS condition"
        ),
    )
    return parser


def _comma_floats(value: str) -> tuple[float, ...]:
    return tuple(float(item) for item in value.split(",") if item.strip())


def _comma_ints(value: str) -> tuple[int, ...]:
    return tuple(int(item) for item in value.split(",") if item.strip())


def _selected_variants(value: str) -> tuple[RQ1Variant, ...]:
    try:
        variants = tuple(
            RQ1Variant(item.strip()) for item in value.split(",") if item.strip()
        )
    except ValueError as exc:
        raise ValueError(f"unknown representation variant: {exc}") from exc
    if not variants or len(set(variants)) != len(variants):
        raise ValueError("variants must be a non-empty unique list")
    return variants


def _static_weights(value: str) -> tuple[tuple[RQ1Variant, float], ...]:
    if not value.strip():
        return ()
    try:
        return tuple(
            (RQ1Variant(name.strip()), float(weight))
            for item in value.split(",")
            for name, weight in (item.split("=", 1),)
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "static weights must use VARIANT=WEIGHT comma-separated syntax"
        ) from exc


def _model(args):
    if args.embedding_backend == "deterministic-hash":
        return (
            DeterministicHashEmbeddingModel(args.hash_dimension),
            "deterministic-hash",
            "cpu",
        )
    config.EMBEDDING_DEVICE = args.device
    from services.embedding.sentence_transformer import STEmbeddingModel

    return STEmbeddingModel(args.model_name), args.model_name, args.device


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        dataset = load_rq1_dataset(args.dataset)
        variants = _selected_variants(args.variants)
        representation_config = RQ1RepresentationConfig(
            IndependentFusion(args.independent_fusion),
            args.key_weight,
            _comma_floats(args.numeric_buckets),
        )
        decision_config = RQ1DecisionConfig(
            args.known_min_similarity,
            args.known_min_margin,
            args.unknown_max_similarity,
        )
        load_started = time.perf_counter_ns()
        model, model_name, device = _model(args)
        cold_load_ms = (time.perf_counter_ns() - load_started) / 1_000_000.0
        conditions = [RQ1Condition(variant.value, (variant,)) for variant in variants]
        if args.include_multiview and len(variants) > 1:
            static_weights = _static_weights(args.static_weights)
            conditions.extend(
                (
                    RQ1Condition("MULTIVIEW_EQUAL_VOTE", variants, "EQUAL_VOTE"),
                    RQ1Condition(
                        "MULTIVIEW_SIMILARITY_AVERAGE",
                        variants,
                        "SIMILARITY_AVERAGE",
                    ),
                    RQ1Condition(
                        "MULTIVIEW_CALIBRATED_STATIC_WEIGHTS",
                        variants,
                        "STATIC_WEIGHTS",
                        static_weights,
                    ),
                )
            )
        elif args.static_weights:
            static_weights = _static_weights(args.static_weights)
            conditions.append(
                RQ1Condition(
                    "MULTIVIEW_CALIBRATED_STATIC_WEIGHTS",
                    variants,
                    "STATIC_WEIGHTS",
                    static_weights,
                )
            )
        runner = RQ1BenchmarkRunner(
            model,
            model_name=model_name,
            device=device,
            representation_config=representation_config,
            decision_config=decision_config,
        )
        result = runner.run(
            dataset,
            tuple(conditions),
            split=RQ1Split(args.split),
            seed=args.seed,
            bootstrap_repetitions=args.bootstrap_repetitions,
            diagnostics=args.diagnostics,
            scale_sizes=_comma_ints(args.scale_sizes),
        )
        result = replace(
            result,
            metadata={**result.metadata, "cold_model_load_ms": cold_load_ms},
        )
        paths = write_rq1_artifacts(result, args.output_dir)
    except (OSError, TypeError, ValueError) as exc:
        _parser().error(str(exc))
    print(f"RQ1 benchmark complete: {len(result.summary_rows)} summary rows")
    for kind, path in paths.items():
        print(f"{kind}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
