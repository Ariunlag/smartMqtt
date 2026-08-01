import json
from pathlib import Path

from services.semantic.evaluation import SemanticBenchmarkBuilder
from services.semantic.evaluation.run_calibration import (
    MODEL_NAME,
    build_artifact,
    build_calibration_evidence,
    derive_threshold_grid,
    generate,
    serialize_artifact,
)


class CountingEmbeddingModel:
    def __init__(self):
        self.calls = []

    def encode(self, texts):
        frozen = tuple(texts)
        self.calls.append(frozen)
        return [
            (float(sum(map(ord, text)) % 97 + 1), float(len(text) + 1))
            for text in frozen
        ]


def test_evidence_uses_reference_and_calibration_once_without_test():
    dataset = SemanticBenchmarkBuilder().build()
    model = CountingEmbeddingModel()

    evidence, dimension = build_calibration_evidence(dataset, model)

    assert len(evidence) == 18
    assert dimension == 2
    assert len(model.calls) == 24  # six REFERENCE + eighteen CALIBRATION inputs
    assert all("/test" not in text for call in model.calls for text in call)
    assert sum(item.is_unseen_class for item in evidence) == 2


def test_grid_and_frontier_are_deterministic_from_reused_evidence():
    dataset = SemanticBenchmarkBuilder().build()
    evidence, dimension = build_calibration_evidence(
        dataset,
        CountingEmbeddingModel(),
    )

    first_grid = derive_threshold_grid(evidence)
    first = build_artifact(dataset, evidence, dimension)
    second = build_artifact(dataset, evidence, dimension)

    assert first_grid == derive_threshold_grid(evidence)
    assert first == second
    assert first["valid_configuration_count"] > 0
    assert first["pareto_frontier"]
    assert "best" not in first
    assert "selected" not in first
    assert "weighted" not in first


def test_injected_generation_is_repeatable_and_never_loads_real_model():
    created = []

    def factory(model_name):
        assert model_name == MODEL_NAME
        model = CountingEmbeddingModel()
        created.append(model)
        return model

    first_path = Path(__file__).with_name(".calibration-result-first.json")
    second_path = Path(__file__).with_name(".calibration-result-second.json")
    try:
        first = generate(model_factory=factory, output_path=first_path)
        second = generate(model_factory=factory, output_path=second_path)

        assert first == second
        assert first_path.read_bytes() == second_path.read_bytes()
        assert first_path.read_bytes().endswith(b"\n")
        assert len(created) == 2
    finally:
        first_path.unlink(missing_ok=True)
        second_path.unlink(missing_ok=True)


def test_committed_artifact_has_exact_metadata_and_no_test_outputs():
    artifact_path = (
        Path(__file__).resolve().parents[2]
        / "docs"
        / "results"
        / "semantic_calibration_frontier.json"
    )
    raw = artifact_path.read_text(encoding="utf-8")
    artifact = json.loads(raw)

    assert artifact["embedding"] == {
        "implementation": "STEmbeddingModel",
        "model_name": "BAAI/bge-small-en-v1.5",
        "device": "cpu",
        "dimension": 384,
        "normalized": True,
    }
    assert artifact["valid_configuration_count"] == 13872
    assert artifact["pareto_frontier_size"] == 40
    assert len(artifact["pareto_frontier"]) == 40
    assert raw == serialize_artifact(artifact)
    assert raw.endswith("\n")
    lowered = raw.lower()
    assert "test" not in lowered
    assert "best" not in lowered
    assert "selected" not in lowered
    assert "weighted" not in lowered
