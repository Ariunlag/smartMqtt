"""Tests for independent representation-specific known-class evidence."""

from dataclasses import FrozenInstanceError

import pytest
from services.semantic import (
    RepresentationClassCentroids,
    RepresentationClassEvidenceMatrix,
    RepresentationClassScorer,
    RepresentationEmbeddings,
    StreamClassEngine,
)

E1 = (1.0, 0.0, 0.0)
E2 = (0.0, 1.0, 0.0)
E3 = (0.0, 0.0, 1.0)
NEG_E1 = (-1.0, 0.0, 0.0)


def _embeddings(**overrides):
    vectors = {
        "value_only": E1,
        "key_only": E1,
        "key_value": E1,
        "schema": E1,
        "numeric_key_only": E1,
        "topic_key_value": E1,
    }
    vectors.update(overrides)
    return RepresentationEmbeddings(**vectors)


def _known_class(class_id="class-a", class_name="Class A", **centroids):
    return RepresentationClassCentroids(
        class_id=class_id,
        class_name=class_name,
        centroids=_embeddings(**centroids),
    )


def test_one_class_produces_exactly_six_independent_scores():
    matrix = RepresentationClassScorer.score(_embeddings(), [_known_class()])

    assert len(matrix.rows) == 1
    assert list(matrix.rows[0].scores.as_dict()) == [
        "value_only",
        "key_only",
        "key_value",
        "schema",
        "numeric_key_only",
        "topic_key_value",
    ]


def test_every_score_uses_its_matching_representation_channel():
    stream = _embeddings(
        value_only=E1,
        key_only=E2,
        key_value=E3,
        schema=(1.0, 1.0, 0.0),
        numeric_key_only=(1.0, -1.0, 0.0),
        topic_key_value=(1.0, 0.0, 1.0),
    )
    centroids = _known_class(
        value_only=E1,
        key_only=(0.0, -1.0, 0.0),
        key_value=E1,
        schema=(1.0, 1.0, 0.0),
        numeric_key_only=(-1.0, 1.0, 0.0),
        topic_key_value=E2,
    )

    scores = RepresentationClassScorer.score(stream, [centroids]).rows[0].scores

    assert scores.value_only == pytest.approx(1.0)
    assert scores.key_only == pytest.approx(-1.0)
    assert scores.key_value == pytest.approx(0.0)
    assert scores.schema == pytest.approx(1.0)
    assert scores.numeric_key_only == pytest.approx(-1.0)
    assert scores.topic_key_value == pytest.approx(0.0)


def test_two_classes_sort_by_id_independent_of_input_order():
    class_b = _known_class("class-b", "B", value_only=E2)
    class_a = _known_class("class-a", "A", value_only=E1)

    matrix = RepresentationClassScorer.score(_embeddings(), [class_b, class_a])

    assert [row.class_id for row in matrix.rows] == ["class-a", "class-b"]


def test_scores_match_stream_class_engine_cosine_similarity():
    stream = _embeddings(schema=(2.0, 1.0, 0.0))
    known_class = _known_class(schema=(1.0, 3.0, 0.0))

    score = RepresentationClassScorer.score(stream, [known_class]).rows[0].scores

    assert score.schema == pytest.approx(
        StreamClassEngine.cosine_similarity(stream.schema, known_class.centroids.schema)
    )


def test_identical_opposite_and_orthogonal_scores_are_preserved():
    stream = _embeddings(value_only=E1, key_only=E1, schema=E1)
    known_class = _known_class(value_only=E1, key_only=NEG_E1, schema=E2)

    scores = RepresentationClassScorer.score(stream, [known_class]).rows[0].scores

    assert scores.value_only == pytest.approx(1.0)
    assert scores.key_only == pytest.approx(-1.0)
    assert scores.schema == pytest.approx(0.0)


def test_view_disagreement_is_preserved_without_a_class_winner():
    stream = _embeddings(key_only=E1, schema=E1)
    class_a = _known_class("class-a", "A", key_only=E1, schema=E2)
    class_b = _known_class("class-b", "B", key_only=E2, schema=E1)

    matrix = RepresentationClassScorer.score(stream, [class_b, class_a])
    rows = {row.class_id: row for row in matrix.rows}

    assert rows["class-a"].scores.key_only > rows["class-b"].scores.key_only
    assert rows["class-b"].scores.schema > rows["class-a"].scores.schema
    assert not hasattr(rows["class-a"], "aggregate_score")
    assert not hasattr(rows["class-a"], "rank")


def test_empty_known_class_input_returns_empty_matrix():
    assert RepresentationClassScorer.score(_embeddings(), []) == (
        RepresentationClassEvidenceMatrix(rows=())
    )


def test_duplicate_class_ids_are_rejected():
    classes = (
        _known_class("class-a", "First"),
        _known_class("class-a", "Second"),
    )

    with pytest.raises(ValueError, match="Duplicate class_id: 'class-a'"):
        RepresentationClassScorer.score(_embeddings(), classes)


@pytest.mark.parametrize("class_id", ["", "   ", None, 1, True])
def test_invalid_class_id_is_rejected(class_id):
    with pytest.raises(ValueError, match="class_id must be a non-empty string"):
        _known_class(class_id=class_id)


@pytest.mark.parametrize("class_name", ["", "   ", None, 1, True])
def test_invalid_class_name_is_rejected(class_name):
    with pytest.raises(ValueError, match="class_name must be a non-empty string"):
        _known_class(class_name=class_name)


def test_dimension_mismatch_has_class_and_representation_context():
    known_class = _known_class("class-a", "A", schema=(1.0,))

    with pytest.raises(
        ValueError,
        match="class 'class-a', representation 'schema'.*dimension mismatch",
    ) as exc_info:
        RepresentationClassScorer.score(_embeddings(), [known_class])

    assert isinstance(exc_info.value.__cause__, ValueError)


def test_zero_norm_stream_representation_is_rejected_with_context():
    stream = _embeddings(key_value=(0.0, 0.0, 0.0))

    with pytest.raises(
        ValueError,
        match="class 'class-a', representation 'key_value'.*zero-norm",
    ):
        RepresentationClassScorer.score(stream, [_known_class()])


def test_zero_norm_class_centroid_is_rejected_with_context():
    known_class = _known_class(topic_key_value=(0.0, 0.0, 0.0))

    with pytest.raises(
        ValueError,
        match="class 'class-a', representation 'topic_key_value'.*zero-norm",
    ):
        RepresentationClassScorer.score(_embeddings(), [known_class])


def test_inputs_are_not_mutated():
    stream = _embeddings()
    known_class = _known_class()
    original_stream = stream.as_dict()
    original_centroids = known_class.centroids.as_dict()

    RepresentationClassScorer.score(stream, [known_class])

    assert stream.as_dict() == original_stream
    assert known_class.centroids.as_dict() == original_centroids


def test_centroid_score_evidence_and_matrix_models_are_immutable():
    known_class = _known_class()
    matrix = RepresentationClassScorer.score(_embeddings(), [known_class])
    evidence = matrix.rows[0]

    with pytest.raises(FrozenInstanceError):
        known_class.class_name = "Changed"
    with pytest.raises(FrozenInstanceError):
        evidence.scores.schema = 0.0
    with pytest.raises(FrozenInstanceError):
        evidence.class_id = "changed"
    with pytest.raises(FrozenInstanceError):
        matrix.rows = ()


def test_serialization_preserves_class_and_six_view_order():
    matrix = RepresentationClassScorer.score(
        _embeddings(),
        [_known_class("class-b", "B"), _known_class("class-a", "A")],
    )

    serialized = matrix.as_dict()

    assert list(serialized) == ["class-a", "class-b"]
    assert serialized["class-a"]["class_name"] == "A"
    assert list(serialized["class-a"]["scores"]) == [
        "value_only",
        "key_only",
        "key_value",
        "schema",
        "numeric_key_only",
        "topic_key_value",
    ]


def test_class_input_may_be_a_generator():
    classes = (
        known_class
        for known_class in (
            _known_class("class-b", "B"),
            _known_class("class-a", "A"),
        )
    )

    matrix = RepresentationClassScorer.score(_embeddings(), classes)

    assert [row.class_id for row in matrix.rows] == ["class-a", "class-b"]


def test_equal_values_remain_six_separate_score_fields():
    scores = (
        RepresentationClassScorer.score(
            _embeddings(),
            [_known_class()],
        )
        .rows[0]
        .scores
    )

    assert tuple(scores.as_dict().values()) == pytest.approx((1.0,) * 6)
    assert len(scores.as_dict()) == 6
    assert not hasattr(scores, "aggregate_score")


def test_duplicate_display_names_are_allowed_for_distinct_ids():
    matrix = RepresentationClassScorer.score(
        _embeddings(),
        [_known_class("class-b", "Shared"), _known_class("class-a", "Shared")],
    )

    assert len(matrix.rows) == 2
