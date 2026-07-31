"""Generate the real, calibration-only semantic threshold frontier artifact."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

from services.embedding.sentence_transformer import STEmbeddingModel

from .benchmark import SemanticBenchmarkBuilder, SemanticBenchmarkScenario
from .calibration import (
    SemanticCalibrationEvidence,
    SemanticDecisionThresholdGrid,
    SemanticThresholdCalibrator,
)
from .experiment import SemanticExperimentRunner, SemanticExperimentVariant
from .calibration import SemanticCalibrationSplit
from ..multi_view_consensus import MultiViewConsensusEngine
from ..representation_class_scoring import RepresentationClassScorer

MODEL_NAME = "BAAI/bge-small-en-v1.5"
DEVICE = "cpu"
ARTIFACT_PATH = Path(__file__).resolve().parents[4] / "docs" / "results" / "semantic_calibration_frontier.json"


def _view(dataset, split):
    scenarios = tuple(
        SemanticBenchmarkScenario(s.scenario_id, s.scenario_type, s.expected_change, tuple(x for x in s.streams if x.split is split))
        for s in dataset.scenarios if any(x.split is split for x in s.streams)
    )
    return SimpleNamespace(known_class_names=dataset.known_class_names, unseen_class_names=dataset.unseen_class_names, scenarios=scenarios)


def generate(model=None):
    dataset = SemanticBenchmarkBuilder().build()
    model = model or STEmbeddingModel(MODEL_NAME)
    runner = SemanticExperimentRunner()
    reference, calibration = _view(dataset, SemanticCalibrationSplit.REFERENCE), _view(dataset, SemanticCalibrationSplit.CALIBRATION)
    classes = runner._reference_classes(reference, model, SemanticExperimentVariant.OPEN_WORLD_MULTI_VIEW)
    evidence = []
    for scenario in calibration.scenarios:
        for stream in scenario.streams:
            for observation in stream.observations:
                embeddings = runner._snapshot_embedding(__import__("services.semantic.representation_embedder", fromlist=["RepresentationEmbedder"]).RepresentationEmbedder(model), observation)
                consensus = MultiViewConsensusEngine.build(RepresentationClassScorer.score(embeddings, classes))
                evidence.append(SemanticCalibrationEvidence(observation.expected_class_name, observation.is_unseen_class, consensus))
    tops = sorted({item.consensus.top_candidate.mean_similarity for item in evidence})
    margins = sorted({0.0} | {item.consensus.classes[0].mean_similarity - item.consensus.classes[1].mean_similarity for item in evidence if len(item.consensus.classes) > 1 and 0 <= item.consensus.classes[0].mean_similarity - item.consensus.classes[1].mean_similarity <= 2})
    grid = SemanticDecisionThresholdGrid((1, 2, 3, 4, 5, 6), tuple(tops), tuple(margins), tuple(tops))
    result = SemanticThresholdCalibrator().calibrate(tuple(evidence), grid)
    dimension = len(runner._snapshot_embedding(__import__("services.semantic.representation_embedder", fromlist=["RepresentationEmbedder"]).RepresentationEmbedder(model), calibration.scenarios[0].streams[0].observations[0]).key_only)
    artifact = {"embedding": {"implementation": "STEmbeddingModel", "model_name": MODEL_NAME, "device": DEVICE, "dimension": dimension, "normalized": True}, "split": {"reference_stream_count": len(dataset.reference_streams), "calibration_stream_count": len(dataset.calibration_streams), "calibration_known_count": sum(not x.is_unseen_class for x in evidence), "calibration_unseen_count": sum(x.is_unseen_class for x in evidence)}, "valid_configuration_count": len(result.all_candidates), "pareto_frontier_size": len(result.pareto_frontier), "pareto_frontier": [{**asdict(c.config), **asdict(c.metrics)} for c in result.pareto_frontier]}
    ARTIFACT_PATH.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT_PATH.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return artifact


if __name__ == "__main__":
    generate()
