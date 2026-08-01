"""Tests for representation-specific HDBSCAN UNKNOWN-stream discovery."""

from collections.abc import Sequence
from dataclasses import FrozenInstanceError
from typing import ClassVar

import pytest
import services.semantic.unknown_stream_discovery as discovery_module
from services.semantic import (
    HDBSCANDiscoveryConfig,
    RepresentationEmbeddings,
    SemanticClassDecision,
    SemanticClassDecisionReason,
    SemanticClassDecisionState,
    UnknownStreamDiscoveryEngine,
    UnknownStreamEntry,
)

VIEW_NAMES = (
    "value_only",
    "key_only",
    "key_value",
    "schema",
    "numeric_key_only",
    "topic_key_value",
)


def _decision():
    return SemanticClassDecision(
        state=SemanticClassDecisionState.UNKNOWN,
        candidate=None,
        runner_up=None,
        similarity_margin=None,
        reasons=(SemanticClassDecisionReason.NO_KNOWN_CLASSES,),
    )


def _embeddings(default=(0.0, 0.0), **overrides):
    vectors = {name: default for name in VIEW_NAMES}
    vectors.update(overrides)
    return RepresentationEmbeddings(**vectors)


def _entry(topic, default=(0.0, 0.0), **overrides):
    return UnknownStreamEntry(topic, _embeddings(default, **overrides), _decision())


def _engine(**overrides):
    values = {"min_cluster_size": 2}
    values.update(overrides)
    return UnknownStreamDiscoveryEngine(HDBSCANDiscoveryConfig(**values))


class _FakeHDBSCAN:
    labels_by_call: ClassVar[list[Sequence[int]]] = []
    calls: ClassVar[list[tuple[dict[str, object], tuple[tuple[float, ...], ...]]]] = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def fit_predict(self, vectors):
        type(self).calls.append((self.kwargs, tuple(tuple(row) for row in vectors)))
        return type(self).labels_by_call.pop(0)


def _install_fake_hdbscan(monkeypatch, labels_by_call):
    _FakeHDBSCAN.labels_by_call = list(labels_by_call)
    _FakeHDBSCAN.calls = []
    monkeypatch.setattr(discovery_module, "HDBSCAN", _FakeHDBSCAN)


def test_empty_input_returns_six_empty_view_results():
    result = _engine().discover(())

    assert (
        tuple(item.representation_name for item in result.representations) == VIEW_NAMES
    )
    assert all(
        item.candidates == () and item.noise_topics == ()
        for item in result.representations
    )


def test_insufficient_samples_returns_all_topics_as_noise_without_clusters():
    result = _engine(min_cluster_size=3).discover(
        [_entry("a/topic"), _entry("b/topic")]
    )

    assert all(item.candidates == () for item in result.representations)
    assert all(
        item.noise_topics == ("a/topic", "b/topic") for item in result.representations
    )


def test_input_order_does_not_change_deterministic_topic_order():
    entries = [_entry("z/topic"), _entry("a/topic")]

    first = _engine(min_cluster_size=3).discover(entries)
    second = _engine(min_cluster_size=3).discover(reversed(entries))

    assert first == second
    assert first.representations[0].noise_topics == ("a/topic", "z/topic")


def test_duplicate_topics_are_rejected():
    with pytest.raises(ValueError, match="Duplicate topic: 'same/topic'"):
        _engine().discover([_entry("same/topic"), _entry("same/topic")])


def test_dimension_mismatch_identifies_representation():
    entries = [
        _entry("a/topic", schema=(0.0, 0.0)),
        _entry("b/topic", schema=(0.0, 0.0, 0.0)),
    ]

    with pytest.raises(ValueError, match="dimension mismatch.*'schema'"):
        _engine().discover(entries)


def test_empty_vector_is_rejected():
    with pytest.raises(
        ValueError, match="representation 'value_only'.*must not be empty"
    ):
        _engine().discover([_entry("a/topic", value_only=())])


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), True])
def test_non_finite_or_bool_vector_component_is_rejected(value):
    with pytest.raises(
        (TypeError, ValueError), match="representation 'value_only'.*real, finite"
    ):
        _engine().discover([_entry("a/topic", value_only=(value, 0.0))])


def test_candidates_are_canonicalized_without_exposing_raw_hdbscan_labels():
    result = _engine()._result_from_labels(
        "schema",
        ("topic-c", "topic-a", "topic-b", "topic-d"),
        (90, 3, 90, -1),
    )

    assert [candidate.candidate_index for candidate in result.candidates] == [0, 1]
    assert [candidate.member_topics for candidate in result.candidates] == [
        ("topic-a",),
        ("topic-b", "topic-c"),
    ]
    assert result.noise_topics == ("topic-d",)
    assert not hasattr(result.candidates[0], "raw_label")
    assert not hasattr(result.candidates[0], "semantic_class_name")


def test_noise_and_cross_view_disagreement_are_retained(monkeypatch):
    _install_fake_hdbscan(
        monkeypatch,
        [(-1, -1), (7, 7), (-1, -1), (-1, -1), (-1, -1), (-1, -1)],
    )

    result = _engine().discover([_entry("b/topic"), _entry("a/topic")])

    assert result.representations[0].noise_topics == ("a/topic", "b/topic")
    assert result.representations[1].candidates[0].member_topics == (
        "a/topic",
        "b/topic",
    )


def test_all_six_representations_are_clustered_independently_without_fusion(
    monkeypatch,
):
    _install_fake_hdbscan(monkeypatch, [(0, 0)] * 6)
    entries = [
        _entry("a/topic", value_only=(1.0, 2.0), key_only=(3.0, 4.0)),
        _entry("b/topic", value_only=(5.0, 6.0), key_only=(7.0, 8.0)),
    ]

    result = _engine().discover(entries)

    assert len(_FakeHDBSCAN.calls) == 6
    assert _FakeHDBSCAN.calls[0][1] == ((1.0, 2.0), (5.0, 6.0))
    assert _FakeHDBSCAN.calls[1][1] == ((3.0, 4.0), (7.0, 8.0))
    assert all(
        len(vector) == 2 for _, matrix in _FakeHDBSCAN.calls for vector in matrix
    )
    assert not hasattr(result, "fused_vector")
    assert not hasattr(result.representations[0], "weighted_score")


def test_configuration_is_passed_explicitly_to_hdbscan(monkeypatch):
    _install_fake_hdbscan(monkeypatch, [(-1, -1)] * 6)
    engine = _engine(
        min_samples=1,
        cluster_selection_epsilon=0.2,
        cluster_selection_method="leaf",
        allow_single_cluster=True,
    )

    engine.discover([_entry("a/topic"), _entry("b/topic")])

    kwargs = _FakeHDBSCAN.calls[0][0]
    assert kwargs == {
        "min_cluster_size": 2,
        "min_samples": 1,
        "cluster_selection_epsilon": 0.2,
        "cluster_selection_method": "leaf",
        "allow_single_cluster": True,
        "metric": "euclidean",
    }


def test_real_hdbscan_finds_canonical_candidates_for_separated_points():
    entries = [
        _entry("cluster-a-1", default=(0.0, 0.0)),
        _entry("cluster-a-2", default=(0.1, 0.0)),
        _entry("cluster-a-3", default=(0.0, 0.1)),
        _entry("cluster-b-1", default=(10.0, 10.0)),
        _entry("cluster-b-2", default=(10.1, 10.0)),
        _entry("cluster-b-3", default=(10.0, 10.1)),
    ]

    result = _engine(min_samples=1).discover(entries)
    view = result.for_representation("value_only")

    assert [candidate.member_topics for candidate in view.candidates] == [
        ("cluster-a-1", "cluster-a-2", "cluster-a-3"),
        ("cluster-b-1", "cluster-b-2", "cluster-b-3"),
    ]
    assert view.noise_topics == ()


def test_result_and_config_models_are_immutable(monkeypatch):
    _install_fake_hdbscan(monkeypatch, [(-1, -1)] * 6)
    config = HDBSCANDiscoveryConfig(min_cluster_size=2)
    result = UnknownStreamDiscoveryEngine(config).discover(
        [_entry("a/topic"), _entry("b/topic")]
    )

    with pytest.raises(FrozenInstanceError):
        config.min_cluster_size = 3
    with pytest.raises(FrozenInstanceError):
        result.representations = ()
    with pytest.raises(FrozenInstanceError):
        result.representations[0].representation_name = "changed"


def test_entries_are_not_mutated_and_repeated_runs_have_equal_public_output():
    entries = [
        _entry("cluster-a-1", default=(0.0, 0.0)),
        _entry("cluster-a-2", default=(0.1, 0.0)),
        _entry("cluster-b-1", default=(10.0, 10.0)),
        _entry("cluster-b-2", default=(10.1, 10.0)),
    ]
    before = tuple(
        (entry.topic, entry.embeddings.as_dict(), entry.decision) for entry in entries
    )
    engine = _engine(min_samples=1)

    first = engine.discover(entries)
    second = engine.discover(entries)

    assert first == second
    assert (
        tuple(
            (entry.topic, entry.embeddings.as_dict(), entry.decision)
            for entry in entries
        )
        == before
    )


@pytest.mark.parametrize(
    "kwargs, error",
    [
        ({"min_cluster_size": 1}, "min_cluster_size must be at least 2"),
        ({"min_samples": 0}, "min_samples must be at least 1"),
        ({"cluster_selection_epsilon": -0.1}, "must be at least 0"),
        ({"cluster_selection_method": "invalid"}, "must be 'eom' or 'leaf'"),
        ({"metric": ""}, "metric must be a non-empty string"),
    ],
)
def test_invalid_configuration_is_rejected(kwargs, error):
    values = {"min_cluster_size": 2}
    values.update(kwargs)

    with pytest.raises(ValueError, match=error):
        HDBSCANDiscoveryConfig(**values)


def test_result_helper_returns_none_for_unknown_representation():
    result = _engine().discover(())

    assert result.for_representation("missing") is None
