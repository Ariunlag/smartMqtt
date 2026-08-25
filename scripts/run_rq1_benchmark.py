"""Run the research-only pair-level class recommendation benchmark."""

from __future__ import annotations

import argparse
import hashlib
import math
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from config import config
from services.class_recommendation.evaluation import (
    RQ1BenchmarkRunner,
    RQ1Split,
    load_rq1_dataset,
    write_rq1_artifacts,
)


class DeterministicHashEmbeddingModel:
    """Dependency-free smoke-test model; never used by production runtime."""

    def __init__(self, dimension: int = 32) -> None:
        self.dimension = dimension

    def encode(self, texts):
        vectors = []
        for text in texts:
            values = [0.0] * self.dimension
            for token in text.lower().split() or ["<empty>"]:
                digest = hashlib.sha256(token.encode()).digest()
                values[int.from_bytes(digest[:4], "big") % self.dimension] += (
                    -1.0 if digest[4] & 1 else 1.0
                )
            norm = math.sqrt(sum(value * value for value in values)) or 1.0
            vectors.append([value / norm for value in values])
        return vectors


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Run SmartMQTT pair-level class recommendation RQ1 evaluation"
    )
    result.add_argument("--dataset", required=True, type=Path)
    result.add_argument("--output-dir", required=True, type=Path)
    result.add_argument("--split", choices=("VALIDATION", "TEST"), default="VALIDATION")
    result.add_argument(
        "--embedding-backend",
        choices=("sentence-transformer", "deterministic-hash"),
        default="sentence-transformer",
    )
    result.add_argument("--model-name", default=config.EMBEDDING_MODEL)
    result.add_argument("--device", default=config.EMBEDDING_DEVICE)
    result.add_argument("--hash-dimension", type=int, default=32)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    dataset = load_rq1_dataset(args.dataset)
    if args.embedding_backend == "deterministic-hash":
        model = DeterministicHashEmbeddingModel(args.hash_dimension)
        model_name, device = "deterministic-hash", "cpu"
    else:
        config.EMBEDDING_DEVICE = args.device
        from services.embedding.sentence_transformer import STEmbeddingModel

        model = STEmbeddingModel(args.model_name)
        model_name, device = args.model_name, args.device
    result = RQ1BenchmarkRunner(model, model_name=model_name, device=device).run(
        dataset, split=RQ1Split(args.split)
    )
    paths = write_rq1_artifacts(result, args.output_dir)
    print(f"RQ1 benchmark complete: {len(result.summary_rows)} conditions")
    for kind, path in paths.items():
        print(f"{kind}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
