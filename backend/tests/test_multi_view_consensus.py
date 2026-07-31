"""Tests for deterministic equal-view multi-view consensus evidence."""

from dataclasses import FrozenInstanceError

import pytest
from services.semantic import (
    MultiViewConsensusEngine,
    MultiViewConsensusResult,
    RepresentationClassConsensus,
    RepresentationClassEvidence,
    RepresentationClassEvidenceMatrix,
    RepresentationClassScores,
    RepresentationViewWinner,
)

VIEW_NAMES = (
    "value_only",
    "key_only",
    "key_value",
    "schema",
    "numeric_key_only",
    "topic_key_value",
)


def _row(class_id, class_name=None, default=0.0, **overrides):
    values = {name: default for name in VIEW_NAMES}
    values.update(overrides)
    return RepresentationClassEvidence(
        class_id=class_id,
        class_name=class_name or class_id,
        scores=RepresentationClassScores(**values),
    )


def _matrix(*rows):
    return RepresentationClassEvidenceMatrix(rows=rows)


def _canonical_disagreement_matrix():
    return _matrix(
        _row(
            "class-a",
            "A",
            value_only=0.3,
            key_only=0.9,
            key_value=0.9,
            schema=0.2,
            numeric_key_only=0.9,
            topic_key_value=0.7,
        ),
        _row(
            "class-b",
            "B",
            value_only=0.9,
            key_only=0.6,
            key_value=0.6,
            schema=0.5,
            numeric_key_only=0.6,
            topic_key_value=0.9,
        ),
        _row(
            "class-c",
            "C",
            value_only=0.1,
            key_only=0.2,
            key_value=0.2,
            schema=0.9,
            numeric_key_only=0.2,
            topic_key_value=0.1,
        ),
    )


def test_one_class_wins_all_six_views():
    result = MultiViewConsensusEngine.build(_matrix(_row("class-a", default=0.4)))

    assert len(result.view_winners) == 6
    assert result.classes[0].top1_votes == 6
    assert result.classes[0].mean_rank == pytest.approx(1.0)


def test_multiple_classes_produce_exactly_six_total_votes():
    result = MultiViewConsensusEngine.build(_canonical_disagreement_matrix())

    assert sum(row.top1_votes for row in result.classes) == 6


def test_canonical_disagreement_preserves_six_winners_and_3_2_1_votes():
    result = MultiViewConsensusEngine.build(_canonical_disagreement_matrix())

    assert [winner.class_id for winner in result.view_winners] == [
        "class-b",
        "class-a",
        "class-a",
        "class-c",
        "class-a",
        "class-b",
    ]
    assert {row.class_id: row.top1_votes for row in result.classes} == {
        "class-a": 3,
        "class-b": 2,
        "class-c": 1,
    }


def test_consensus_classes_sort_by_vote_count_descending():
    result = MultiViewConsensusEngine.build(_canonical_disagreement_matrix())

    assert [row.class_id for row in result.classes] == [
        "class-a",
        "class-b",
        "class-c",
    ]


def test_vote_tie_is_broken_by_lower_mean_rank():
    result = MultiViewConsensusEngine.build(
        _matrix(
            _row(
                "class-a",
                value_only=0.9,
                key_only=0.9,
                key_value=0.9,
                schema=0.8,
                numeric_key_only=0.8,
                topic_key_value=0.8,
            ),
            _row(
                "class-b",
                value_only=0.1,
                key_only=0.1,
                key_value=0.1,
                schema=0.9,
                numeric_key_only=0.9,
                topic_key_value=0.9,
            ),
            _row(
                "class-c",
                value_only=0.8,
                key_only=0.8,
                key_value=0.8,
                schema=0.1,
                numeric_key_only=0.1,
                topic_key_value=0.1,
            ),
        )
    )

    rows = {row.class_id: row for row in result.classes}
    assert rows["class-a"].top1_votes == rows["class-b"].top1_votes == 3
    assert rows["class-a"].mean_rank < rows["class-b"].mean_rank
    assert result.classes[0].class_id == "class-a"


def test_vote_and_mean_rank_tie_is_broken_by_higher_mean_similarity():
    result = MultiViewConsensusEngine.build(
        _matrix(
            _row(
                "class-a",
                value_only=0.9,
                key_only=0.9,
                key_value=0.9,
                schema=0.8,
                numeric_key_only=0.8,
                topic_key_value=0.8,
            ),
            _row(
                "class-b",
                value_only=0.7,
                key_only=0.7,
                key_value=0.7,
                schema=0.81,
                numeric_key_only=0.81,
                topic_key_value=0.81,
            ),
        )
    )

    first, second = result.classes
    assert first.top1_votes == second.top1_votes == 3
    assert first.mean_rank == second.mean_rank
    assert first.mean_similarity > second.mean_similarity
    assert first.class_id == "class-a"


def test_complete_numerical_consensus_tie_uses_class_id():
    result = MultiViewConsensusEngine.build(
        _matrix(
            _row(
                "class-b",
                value_only=0.8,
                key_only=0.8,
                key_value=0.8,
                schema=0.9,
                numeric_key_only=0.9,
                topic_key_value=0.9,
            ),
            _row(
                "class-a",
                value_only=0.9,
                key_only=0.9,
                key_value=0.9,
                schema=0.8,
                numeric_key_only=0.8,
                topic_key_value=0.8,
            ),
        )
    )

    assert result.classes[0].top1_votes == result.classes[1].top1_votes
    assert result.classes[0].mean_rank == result.classes[1].mean_rank
    assert result.classes[0].mean_similarity == result.classes[1].mean_similarity
    assert [row.class_id for row in result.classes] == ["class-a", "class-b"]


def test_per_view_ranking_uses_descending_similarity():
    result = MultiViewConsensusEngine.build(
        _matrix(
            _row("class-low", default=-0.5),
            _row("class-high", default=0.7),
            _row("class-middle", default=0.1),
        )
    )
    rows = {row.class_id: row for row in result.classes}

    assert all(winner.class_id == "class-high" for winner in result.view_winners)
    assert rows["class-high"].mean_rank == pytest.approx(1.0)
    assert rows["class-middle"].mean_rank == pytest.approx(2.0)
    assert rows["class-low"].mean_rank == pytest.approx(3.0)


def test_exact_view_score_tie_uses_class_id_for_winner_and_rank():
    result = MultiViewConsensusEngine.build(
        _matrix(_row("class-b", default=0.8), _row("class-a", default=0.8))
    )
    rows = {row.class_id: row for row in result.classes}

    assert all(winner.class_id == "class-a" for winner in result.view_winners)
    assert rows["class-a"].mean_rank == pytest.approx(1.0)
    assert rows["class-b"].mean_rank == pytest.approx(2.0)


def test_mean_rank_is_arithmetic_mean_of_six_positions():
    result = MultiViewConsensusEngine.build(_canonical_disagreement_matrix())
    rows = {row.class_id: row for row in result.classes}

    assert rows["class-a"].mean_rank == pytest.approx((2 + 1 + 1 + 3 + 1 + 2) / 6)


def test_mean_similarity_is_unweighted_arithmetic_mean():
    row = _row(
        "class-a",
        value_only=-1.0,
        key_only=-0.5,
        key_value=0.0,
        schema=0.25,
        numeric_key_only=0.75,
        topic_key_value=1.0,
    )

    result = MultiViewConsensusEngine.build(_matrix(row))

    assert result.classes[0].mean_similarity == pytest.approx(0.5 / 6)


def test_negative_cosine_similarities_are_ranked_normally():
    result = MultiViewConsensusEngine.build(
        _matrix(_row("class-b", default=-0.8), _row("class-a", default=-0.2))
    )

    assert all(winner.class_id == "class-a" for winner in result.view_winners)
    assert result.classes[0].mean_similarity == pytest.approx(-0.2)


def test_empty_matrix_returns_empty_result_and_no_top_candidate():
    result = MultiViewConsensusEngine.build(_matrix())

    assert result == MultiViewConsensusResult(view_winners=(), classes=())
    assert result.top_candidate is None


def test_non_empty_top_candidate_is_first_consensus_row():
    result = MultiViewConsensusEngine.build(_canonical_disagreement_matrix())

    assert result.top_candidate is result.classes[0]


def test_view_winners_follow_exact_six_view_order():
    result = MultiViewConsensusEngine.build(_canonical_disagreement_matrix())

    assert tuple(winner.representation_name for winner in result.view_winners) == (
        VIEW_NAMES
    )


def test_every_class_remains_present_even_without_a_top1_vote():
    result = MultiViewConsensusEngine.build(
        _matrix(
            _row("class-a", default=0.9),
            _row("class-b", default=0.5),
            _row("class-c", default=0.1),
        )
    )

    assert {row.class_id for row in result.classes} == {
        "class-a",
        "class-b",
        "class-c",
    }
    assert {row.class_id: row.top1_votes for row in result.classes}["class-c"] == 0


@pytest.mark.parametrize("invalid_score", [float("nan"), float("inf"), -float("inf")])
def test_non_finite_score_is_rejected(invalid_score):
    matrix = _matrix(_row("class-a", schema=invalid_score))

    with pytest.raises(
        ValueError,
        match="class 'class-a', representation 'schema'.*numeric and finite",
    ):
        MultiViewConsensusEngine.build(matrix)


@pytest.mark.parametrize("invalid_score", ["0.5", None, True])
def test_non_numeric_score_is_rejected(invalid_score):
    matrix = _matrix(_row("class-a", key_only=invalid_score))

    with pytest.raises(
        TypeError,
        match="class 'class-a', representation 'key_only'.*numeric and finite",
    ):
        MultiViewConsensusEngine.build(matrix)


def test_duplicate_class_ids_are_rejected_defensively():
    matrix = _matrix(_row("class-a", "First"), _row("class-a", "Second"))

    with pytest.raises(ValueError, match="Duplicate class_id: 'class-a'"):
        MultiViewConsensusEngine.build(matrix)


def test_input_matrix_is_not_mutated():
    matrix = _canonical_disagreement_matrix()
    before = matrix.as_dict()

    MultiViewConsensusEngine.build(matrix)

    assert matrix.as_dict() == before


def test_public_consensus_models_are_immutable():
    result = MultiViewConsensusEngine.build(_canonical_disagreement_matrix())

    with pytest.raises(FrozenInstanceError):
        result.view_winners[0].class_id = "changed"
    with pytest.raises(FrozenInstanceError):
        result.classes[0].top1_votes = 0
    with pytest.raises(FrozenInstanceError):
        result.classes = ()


def test_caller_class_order_does_not_change_consensus():
    matrix = _canonical_disagreement_matrix()
    reversed_matrix = _matrix(*reversed(matrix.rows))

    assert MultiViewConsensusEngine.build(matrix) == MultiViewConsensusEngine.build(
        reversed_matrix
    )


def test_result_has_no_weighted_or_final_score_or_class_decision():
    result = MultiViewConsensusEngine.build(_canonical_disagreement_matrix())

    assert not hasattr(result, "representation_weights")
    assert not hasattr(result.classes[0], "weighted_score")
    assert not hasattr(result.classes[0], "final_score")
    assert not hasattr(result, "decision")
    assert not hasattr(result, "is_known")


def test_view_winner_preserves_class_name_and_similarity():
    result = MultiViewConsensusEngine.build(
        _matrix(_row("class-a", "Display A", default=0.6))
    )

    winner = result.view_winners[0]
    assert winner.class_name == "Display A"
    assert winner.similarity == pytest.approx(0.6)


def test_public_models_can_be_constructed_with_explicit_evidence():
    winner = RepresentationViewWinner("schema", "class-a", "A", 0.8)
    consensus = RepresentationClassConsensus("class-a", "A", 2, 1.5, 0.7)
    result = MultiViewConsensusResult((winner,), (consensus,))

    assert result.top_candidate == consensus
