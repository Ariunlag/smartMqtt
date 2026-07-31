from dataclasses import FrozenInstanceError

import pytest
from services.semantic import SemanticClassDecisionConfig, SemanticClassDecisionState
from services.semantic.evaluation import (
    SemanticBenchmarkBuilder,
    SemanticExperimentRunner,
    SemanticExperimentVariant,
)


class FakeEmbeddingModel:
    """Stable, dependency-free vectors derived from representation text."""

    def encode(self, texts):
        return [
            (float(sum(map(ord, text)) % 97 + 1), float(len(text) + 1))
            for text in texts
        ]


def _run(variant, config=None):
    return SemanticExperimentRunner().run(
        SemanticBenchmarkBuilder().build(), variant, FakeEmbeddingModel(), config
    )


def test_runs_are_deterministic_and_predictions_are_ordered():
    first = _run(SemanticExperimentVariant.STATIC_MULTI_VIEW)
    second = _run(SemanticExperimentVariant.STATIC_MULTI_VIEW)

    assert first == second
    assert [item.observation_index for item in first.predictions] == [
        0,
        1,
        2,
        0,
        1,
        0,
        1,
        2,
        3,
        0,
        1,
        0,
        1,
        2,
        0,
        1,
        0,
        1,
    ]
    assert len(first.predictions) == 18


@pytest.mark.parametrize(
    "variant",
    (
        SemanticExperimentVariant.SINGLE_VIEW_KEY_ONLY,
        SemanticExperimentVariant.SINGLE_VIEW_SCHEMA,
        SemanticExperimentVariant.STATIC_MULTI_VIEW,
        SemanticExperimentVariant.TEMPORAL_MULTI_VIEW,
    ),
)
def test_non_open_world_variants_produce_known_class_baseline_predictions(variant):
    result = _run(variant)

    assert all(item.decision_state is None for item in result.predictions)
    assert all(item.predicted_class_name is not None for item in result.predictions)


def test_open_world_requires_explicit_config_and_retains_unknown_state():
    with pytest.raises(ValueError, match="requires decision_config"):
        _run(SemanticExperimentVariant.OPEN_WORLD_MULTI_VIEW)

    result = _run(
        SemanticExperimentVariant.OPEN_WORLD_MULTI_VIEW,
        SemanticClassDecisionConfig(1, 1.0, 0.0, 1.0),
    )

    assert all(
        item.decision_state is SemanticClassDecisionState.UNKNOWN
        for item in result.predictions
    )
    assert result.metrics.false_unknown_rate == 1.0


def test_held_out_classes_do_not_become_known_reference_predictions():
    result = _run(SemanticExperimentVariant.SINGLE_VIEW_KEY_ONLY)
    unseen = [item for item in result.predictions if item.is_unseen_class]

    assert unseen
    assert all(item.predicted_class_name != "Vibration Sensor" for item in unseen)


def test_temporal_refresh_metrics_do_not_count_numeric_drift_as_false_refresh():
    result = _run(SemanticExperimentVariant.TEMPORAL_MULTI_VIEW)

    assert result.metrics.semantic_refresh_count > 0
    assert result.metrics.false_refresh_count == 0


def test_result_models_are_immutable_and_zero_unknown_denominators_are_zero():
    result = _run(SemanticExperimentVariant.STATIC_MULTI_VIEW)

    with pytest.raises(FrozenInstanceError):
        result.variant = SemanticExperimentVariant.SINGLE_VIEW_SCHEMA
    assert result.metrics.unknown_precision == 0.0
    assert result.metrics.unknown_recall == 0.0
