"""Generate the real, calibration-only semantic threshold frontier artifact."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

from services.embedding.base_model import BaseEmbeddingModel
from services.embedding.sentence_transformer import STEmbeddingModel

from ..multi_view_consensus import MultiViewConsensusEngine
from ..representation_class_scoring import RepresentationClassScorer
from ..representation_embedder import RepresentationEmbedder
from .benchmark import (
    SemanticBenchmarkBuilder,
    SemanticBenchmarkDataset,
    SemanticBenchmarkScenario,
)
from .calibration import (
    SemanticCalibrationEvidence,
    SemanticCalibrationSplit,
    SemanticDecisionThresholdGrid,
    SemanticThresholdCalibrator,
)
from .experiment import SemanticExperimentRunner, SemanticExperimentVariant

MODEL_NAME = "BAAI/bge-small-en-v1.5"
DEVICE = "cpu"
ARTIFACT_PATH = (
    Path(__file__).resolve().parents[4]
    / "docs"
    / "results"
    / "semantic_calibration_frontier.json"
)


def _view(dataset: SemanticBenchmarkDataset, split: SemanticCalibrationSplit):
    scenarios = tuple(
        SemanticBenchmarkScenario(
            scenario.scenario_id,
            scenario.scenario_type,
            scenario.expected_change,
            tuple(stream for stream in scenario.streams if stream.split is split),
        )
        for scenario in dataset.scenarios
        if any(stream.split is split for stream in scenario.streams)
    )
    return SimpleNamespace(
        known_class_names=dataset.known_class_names,
        unseen_class_names=dataset.unseen_class_names,
        scenarios=scenarios,
    )


def build_calibration_evidence(
    dataset: SemanticBenchmarkDataset,
    model: BaseEmbeddingModel,
) -> tuple[tuple[SemanticCalibrationEvidence, ...], int]:
    """Embed REFERENCE/CALIBRATION inputs once and return reusable consensus."""
    runner = SemanticExperimentRunner()
    reference = _view(dataset, SemanticCalibrationSplit.REFERENCE)
    calibration = _view(dataset, SemanticCalibrationSplit.CALIBRATION)
    classes = runner._reference_classes(
        reference,
        model,
        SemanticExperimentVariant.OPEN_WORLD_MULTI_VIEW,
    )
    embedder = RepresentationEmbedder(model)
    evidence = []
    dimension = None
    for scenario in calibration.scenarios:
        for stream in scenario.streams:
            for observation in stream.observations:
                embeddings = runner._snapshot_embedding(embedder, observation)
                if dimension is None:
                    dimension = len(embeddings.key_only)
                consensus = MultiViewConsensusEngine.build(
                    RepresentationClassScorer.score(embeddings, classes)
                )
                evidence.append(
                    SemanticCalibrationEvidence(
                        observation.expected_class_name,
                        observation.is_unseen_class,
                        consensus,
                    )
                )
    if dimension is None:
        raise ValueError("CALIBRATION split must contain observations")
    return tuple(evidence), dimension


def derive_threshold_grid(
    evidence: tuple[SemanticCalibrationEvidence, ...],
) -> SemanticDecisionThresholdGrid:
    """Derive deterministic boundaries from reusable CALIBRATION evidence."""
    top_similarities = tuple(
        sorted({item.consensus.top_candidate.mean_similarity for item in evidence})
    )
    margins = {0.0}
    for item in evidence:
        if len(item.consensus.classes) > 1:
            margin = (
                item.consensus.classes[0].mean_similarity
                - item.consensus.classes[1].mean_similarity
            )
            if 0.0 <= margin <= 2.0:
                margins.add(margin)
    return SemanticDecisionThresholdGrid(
        known_min_top1_votes=(1, 2, 3, 4, 5, 6),
        known_min_mean_similarity=top_similarities,
        known_min_similarity_margin=tuple(sorted(margins)),
        unknown_max_mean_similarity=top_similarities,
    )


def build_artifact(
    dataset: SemanticBenchmarkDataset,
    evidence: tuple[SemanticCalibrationEvidence, ...],
    dimension: int,
) -> dict[str, object]:
    """Calibrate once over reusable evidence and return deterministic data."""
    result = SemanticThresholdCalibrator().calibrate(
        evidence,
        derive_threshold_grid(evidence),
    )
    return {
        "embedding": {
            "implementation": "STEmbeddingModel",
            "model_name": MODEL_NAME,
            "device": DEVICE,
            "dimension": dimension,
            "normalized": True,
        },
        "split": {
            "reference_stream_count": len(dataset.reference_streams),
            "calibration_stream_count": len(dataset.calibration_streams),
            "calibration_known_count": sum(
                not item.is_unseen_class for item in evidence
            ),
            "calibration_unseen_count": sum(item.is_unseen_class for item in evidence),
        },
        "valid_configuration_count": len(result.all_candidates),
        "pareto_frontier_size": len(result.pareto_frontier),
        "pareto_frontier": [
            {**asdict(candidate.config), **asdict(candidate.metrics)}
            for candidate in result.pareto_frontier
        ],
    }


def serialize_artifact(artifact: dict[str, object]) -> str:
    """Return canonical JSON with stable keys, indentation, and trailing LF."""
    return json.dumps(artifact, indent=2, sort_keys=True) + "\n"


def generate(
    *,
    model_factory: Callable[[str], BaseEmbeddingModel] | None = None,
    output_path: Path = ARTIFACT_PATH,
    dataset: SemanticBenchmarkDataset | None = None,
) -> dict[str, object]:
    """Generate CALIBRATION results without reading or executing TEST streams."""
    benchmark = dataset or SemanticBenchmarkBuilder().build()
    factory = model_factory or STEmbeddingModel
    model = factory(MODEL_NAME)
    evidence, dimension = build_calibration_evidence(benchmark, model)
    artifact = build_artifact(benchmark, evidence, dimension)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(serialize_artifact(artifact), encoding="utf-8")
    return artifact


if __name__ == "__main__":
    generate()
