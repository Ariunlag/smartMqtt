"""Isolated tests for stream semantic class models and vector math."""

from dataclasses import FrozenInstanceError

import pytest
from services.semantic import (
    ClassMatch,
    StreamClassEngine,
    StreamClassMember,
    StreamSemanticClass,
)


def test_centroid_of_one_vector_equals_that_vector():
    assert StreamClassEngine.compute_centroid([(2.0, -1.0)]) == (2.0, -1.0)


def test_centroid_of_multiple_vectors_is_arithmetic_mean():
    centroid = StreamClassEngine.compute_centroid(
        [
            (2.0, 4.0, 6.0),
            (4.0, 8.0, 12.0),
            (6.0, 12.0, 18.0),
        ]
    )

    assert centroid == (4.0, 8.0, 12.0)


def test_incremental_update_matches_full_recomputation():
    initial_vectors = [(1.0, 3.0), (3.0, 5.0)]
    old_centroid = StreamClassEngine.compute_centroid(initial_vectors)
    new_vector = (8.0, 10.0)

    updated = StreamClassEngine.update_centroid(
        old_centroid,
        len(initial_vectors),
        new_vector,
    )
    recomputed = StreamClassEngine.compute_centroid([*initial_vectors, new_vector])

    assert updated == recomputed


def test_mismatched_dimensions_raise_clear_errors():
    with pytest.raises(ValueError, match="Vector dimension mismatch"):
        StreamClassEngine.compute_centroid([(1.0, 2.0), (1.0,)])

    with pytest.raises(ValueError, match="Vector dimension mismatch"):
        StreamClassEngine.update_centroid((1.0, 2.0), 2, (1.0,))

    with pytest.raises(ValueError, match="Vector dimension mismatch"):
        StreamClassEngine.cosine_similarity((1.0, 2.0), (1.0,))


def test_missing_and_empty_vectors_raise_clear_errors():
    with pytest.raises(ValueError, match="At least one vector is required"):
        StreamClassEngine.compute_centroid([])

    with pytest.raises(ValueError, match="vector 0 must not be empty"):
        StreamClassEngine.compute_centroid([()])

    with pytest.raises(ValueError, match="new vector must not be empty"):
        StreamClassEngine.update_centroid((1.0,), 1, ())

    with pytest.raises(ValueError, match="stream vector must not be empty"):
        StreamClassEngine.rank_classes((), ())


def test_incremental_update_requires_existing_member_count():
    with pytest.raises(ValueError, match="old_count must be at least 1"):
        StreamClassEngine.update_centroid((1.0,), 0, (2.0,))


def test_cosine_similarity_for_identical_orthogonal_and_opposite_vectors():
    assert StreamClassEngine.cosine_similarity(
        (1.0, 2.0),
        (1.0, 2.0),
    ) == pytest.approx(1.0)
    assert StreamClassEngine.cosine_similarity(
        (1.0, 0.0),
        (0.0, 1.0),
    ) == pytest.approx(0.0)
    assert StreamClassEngine.cosine_similarity(
        (1.0, 0.0),
        (-1.0, 0.0),
    ) == pytest.approx(-1.0)


def test_cosine_similarity_rejects_zero_norm_vectors():
    with pytest.raises(
        ValueError,
        match="undefined for zero-norm vectors",
    ):
        StreamClassEngine.cosine_similarity((0.0, 0.0), (1.0, 0.0))


def test_rank_classes_returns_descending_similarity_order():
    classes = (
        StreamSemanticClass("opposite", "Opposite", (-1.0, 0.0), 2),
        StreamSemanticClass("diagonal", "Diagonal", (1.0, 1.0), 3),
        StreamSemanticClass("same", "Same", (1.0, 0.0), 4),
    )

    matches = StreamClassEngine.rank_classes((1.0, 0.0), classes)

    assert [match.class_id for match in matches] == [
        "same",
        "diagonal",
        "opposite",
    ]
    assert matches[0].similarity == pytest.approx(1.0)
    assert matches[-1].similarity == pytest.approx(-1.0)


def test_rank_classes_uses_class_id_for_deterministic_ties():
    classes = (
        StreamSemanticClass("class-b", "B", (1.0, 0.0), 1),
        StreamSemanticClass("class-a", "A", (2.0, 0.0), 1),
    )

    matches = StreamClassEngine.rank_classes((3.0, 0.0), classes)

    assert [match.class_id for match in matches] == ["class-a", "class-b"]
    assert matches[0].similarity == pytest.approx(matches[1].similarity)


def test_empty_class_collection_returns_empty_ranking():
    assert StreamClassEngine.rank_classes((1.0,), ()) == ()


def test_domain_models_and_results_are_immutable():
    member = StreamClassMember("factory/sensor1", (1.0, 0.0))
    stream_class = StreamSemanticClass(
        "temperature",
        "Temperature Sensor",
        (1.0, 0.0),
        1,
    )
    match = ClassMatch("temperature", "Temperature Sensor", 1.0)

    with pytest.raises(FrozenInstanceError):
        member.topic = "factory/sensor2"
    with pytest.raises(FrozenInstanceError):
        stream_class.member_count = 2
    with pytest.raises(FrozenInstanceError):
        match.similarity = 0.5
