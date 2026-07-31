from dataclasses import FrozenInstanceError

import pytest
from services.semantic.evaluation import (
    SemanticBenchmarkBuilder,
    SemanticBenchmarkChangeType,
    SemanticBenchmarkDataset,
    SemanticBenchmarkObservation,
    SemanticBenchmarkScenario,
    SemanticBenchmarkScenarioType,
    SemanticBenchmarkStream,
)


def _dataset():
    return SemanticBenchmarkBuilder().build()


def _scenario(dataset, scenario_type):
    return next(
        item for item in dataset.scenarios if item.scenario_type is scenario_type
    )


def test_builder_is_deterministic_and_has_all_required_scenarios():
    first = _dataset()
    second = _dataset()

    assert first == second
    assert {item.scenario_type for item in first.scenarios} == set(
        SemanticBenchmarkScenarioType
    )
    assert tuple(item.scenario_id for item in first.scenarios) == (
        "benign-numeric-drift",
        "identifier-change",
        "stable-metadata-change",
        "key-addition",
        "key-removal",
        "type-change",
        "new-unseen-class",
    )


def test_benign_drift_and_identifier_change_preserve_their_classes():
    dataset = _dataset()
    drift = _scenario(dataset, SemanticBenchmarkScenarioType.BENIGN_NUMERIC_DRIFT)
    identifier = _scenario(dataset, SemanticBenchmarkScenarioType.IDENTIFIER_CHANGE)

    assert [item.fields["temperature"] for item in drift.streams[0].observations] == [
        21.0,
        21.8,
        22.4,
    ]
    assert {item.expected_class_name for item in drift.streams[0].observations} == {
        "Temperature Sensor"
    }
    assert [item.tags["sensor_id"] for item in identifier.streams[0].observations] == [
        "a01",
        "b77",
    ]
    assert identifier.expected_change is SemanticBenchmarkChangeType.BENIGN_EVOLUTION


def test_context_and_structural_scenarios_explicitly_encode_changes():
    dataset = _dataset()
    metadata = _scenario(dataset, SemanticBenchmarkScenarioType.STABLE_METADATA_CHANGE)
    addition = _scenario(dataset, SemanticBenchmarkScenarioType.KEY_ADDITION)
    removal = _scenario(dataset, SemanticBenchmarkScenarioType.KEY_REMOVAL)
    type_change = _scenario(dataset, SemanticBenchmarkScenarioType.TYPE_CHANGE)

    assert [item.tags["location"] for item in metadata.streams[0].observations] == [
        "room_a",
        "room_a",
        "room_b",
        "room_b",
    ]
    assert "lane" not in addition.streams[0].observations[0].fields
    assert "lane" in addition.streams[0].observations[1].fields
    assert all(
        "voltage" not in item.fields for item in removal.streams[0].observations[1:]
    )
    assert type(type_change.streams[0].observations[0].fields["occupied"]) is not type(
        type_change.streams[0].observations[1].fields["occupied"]
    )


def test_known_unseen_split_is_explicit_disjoint_and_labels_observations():
    dataset = _dataset()
    unseen = _scenario(dataset, SemanticBenchmarkScenarioType.NEW_UNSEEN_CLASS)

    assert not set(dataset.known_class_names) & set(dataset.unseen_class_names)
    assert "Vibration Sensor" in dataset.unseen_class_names
    assert len(dataset.known_class_names) == 6
    for scenario in dataset.scenarios:
        for stream in scenario.streams:
            for observation in stream.observations:
                class_names = (
                    dataset.unseen_class_names
                    if observation.is_unseen_class
                    else dataset.known_class_names
                )
                assert observation.expected_class_name in class_names
    assert all(item.is_unseen_class for item in unseen.streams[0].observations)


def test_stream_topics_and_observation_indices_are_deterministic_and_ordered():
    dataset = _dataset()

    topics = [
        stream.topic for scenario in dataset.scenarios for stream in scenario.streams
    ]
    assert topics == [
        stream.topic for scenario in _dataset().scenarios for stream in scenario.streams
    ]
    assert len(topics) == 20
    assert all(
        [item.observation_index for item in stream.observations]
        == sorted(item.observation_index for item in stream.observations)
        for scenario in dataset.scenarios
        for stream in scenario.streams
    )


def test_invalid_stream_and_dataset_inputs_are_rejected():
    observation = SemanticBenchmarkObservation(
        0, "topic/a", {}, {"value": 1}, "Known", False
    )
    stream = SemanticBenchmarkStream("topic/a", "Known", (observation,))

    with pytest.raises(ValueError, match="duplicate stream identity"):
        SemanticBenchmarkScenario(
            "scenario",
            SemanticBenchmarkScenarioType.KEY_ADDITION,
            SemanticBenchmarkChangeType.MEANINGFUL_SEMANTIC_CONTEXT_CHANGE,
            (stream, stream),
        )
    with pytest.raises(ValueError, match="unique"):
        SemanticBenchmarkStream("topic/a", "Known", (observation, observation))
    with pytest.raises(ValueError, match="topic"):
        SemanticBenchmarkObservation(0, "", {}, {}, "Known", False)
    with pytest.raises(ValueError, match="class"):
        SemanticBenchmarkObservation(0, "topic/a", {}, {}, "", False)
    with pytest.raises(ValueError, match="empty"):
        SemanticBenchmarkStream("topic/a", "Known", ())
    with pytest.raises(ValueError, match="overlap"):
        SemanticBenchmarkDataset(
            ("Known",),
            ("Known",),
            (
                SemanticBenchmarkScenario(
                    "scenario",
                    SemanticBenchmarkScenarioType.KEY_ADDITION,
                    SemanticBenchmarkChangeType.MEANINGFUL_SEMANTIC_CONTEXT_CHANGE,
                    (stream,),
                ),
            ),
        )


def test_models_and_structured_inputs_are_immutable_and_have_no_derived_outputs():
    dataset = _dataset()
    observation = dataset.scenarios[0].streams[0].observations[0]

    with pytest.raises(FrozenInstanceError):
        observation.topic = "other"
    with pytest.raises(TypeError):
        observation.tags["location"] = "other"
    assert not hasattr(observation, "embeddings")
    assert not hasattr(dataset, "clusters")
    assert not hasattr(observation, "prediction")
