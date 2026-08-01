from dataclasses import FrozenInstanceError

import pytest
from services.semantic import SemanticClassDecisionConfig
from services.semantic.evaluation import (
    FrozenSemanticBenchmarkConfig,
    SemanticBenchmarkBuilder,
    SemanticBenchmarkExecutor,
    SemanticExperimentVariant,
)


class FakeEmbeddingModel:
    def encode(self, texts):
        return [
            (float(sum(map(ord, text)) % 97 + 1), float(len(text) + 1))
            for text in texts
        ]


def _execute():
    return SemanticBenchmarkExecutor().execute(
        SemanticBenchmarkBuilder().build(),
        FrozenSemanticBenchmarkConfig(SemanticClassDecisionConfig(1, 1.0, 0.0, 1.0)),
        FakeEmbeddingModel(),
    )


def test_executes_all_variants_deterministically_from_reference_and_test_only():
    first = _execute()
    second = _execute()

    assert first == second
    assert [run.variant for run in first.runs] == list(SemanticExperimentVariant)
    assert first.reference_stream_count == 6
    assert first.test_stream_count == 7
    assert all(
        "/test" in prediction.topic
        for run in first.runs
        for prediction in run.result.predictions
    )
    assert all(
        "/calibration" not in prediction.topic
        for run in first.runs
        for prediction in run.result.predictions
    )


def test_frozen_config_and_summary_rows_are_preserved_and_immutable():
    comparison = _execute()

    assert (
        comparison.runs[-1].result.variant
        is SemanticExperimentVariant.OPEN_WORLD_MULTI_VIEW
    )
    assert comparison.frozen_config.decision_config == SemanticClassDecisionConfig(
        1, 1.0, 0.0, 1.0
    )
    assert [row["variant"] for row in comparison.summary_rows()] == [
        item.value for item in SemanticExperimentVariant
    ]
    with pytest.raises(FrozenInstanceError):
        comparison.runs = ()
