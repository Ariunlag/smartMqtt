"""Tests for the configurable open-world semantic class decision policy."""

from dataclasses import FrozenInstanceError

import pytest
from services.semantic import (
    MultiViewConsensusResult,
    RepresentationClassConsensus,
    SemanticClassDecisionConfig,
    SemanticClassDecisionPolicy,
    SemanticClassDecisionReason,
    SemanticClassDecisionState,
)


def _config(**overrides):
    values = {
        "known_min_top1_votes": 4,
        "known_min_mean_similarity": 0.7,
        "known_min_similarity_margin": 0.1,
        "unknown_max_mean_similarity": 0.3,
    }
    values.update(overrides)
    return SemanticClassDecisionConfig(**values)


def _candidate(
    class_id="class-a",
    class_name="Class A",
    top1_votes=5,
    mean_rank=1.2,
    mean_similarity=0.8,
):
    return RepresentationClassConsensus(
        class_id=class_id,
        class_name=class_name,
        top1_votes=top1_votes,
        mean_rank=mean_rank,
        mean_similarity=mean_similarity,
    )


def _consensus(*classes):
    return MultiViewConsensusResult(view_winners=(), classes=classes)


def _decide(consensus, **config_overrides):
    return SemanticClassDecisionPolicy(_config(**config_overrides)).decide(consensus)


def test_empty_consensus_is_unknown_without_candidates():
    decision = _decide(_consensus())

    assert decision.state is SemanticClassDecisionState.UNKNOWN
    assert decision.candidate is None
    assert decision.runner_up is None
    assert decision.similarity_margin is None
    assert decision.reasons == (SemanticClassDecisionReason.NO_KNOWN_CLASSES,)


def test_strong_candidate_meeting_all_criteria_is_known():
    decision = _decide(
        _consensus(
            _candidate(mean_similarity=0.85),
            _candidate("class-b", "Class B", 1, 2.0, 0.6),
        )
    )

    assert decision.state is SemanticClassDecisionState.KNOWN
    assert decision.reasons == (SemanticClassDecisionReason.KNOWN_CRITERIA_MET,)


def test_exact_known_vote_threshold_passes():
    decision = _decide(
        _consensus(
            _candidate(top1_votes=4, mean_similarity=0.85),
            _candidate("class-b", "Class B", 2, 2.0, 0.6),
        )
    )

    assert decision.state is SemanticClassDecisionState.KNOWN


def test_exact_known_similarity_threshold_passes():
    decision = _decide(
        _consensus(
            _candidate(mean_similarity=0.7),
            _candidate("class-b", "Class B", 1, 2.0, 0.5),
        )
    )

    assert decision.state is SemanticClassDecisionState.KNOWN


def test_exact_similarity_margin_threshold_passes():
    decision = _decide(
        _consensus(
            _candidate(mean_similarity=0.8),
            _candidate("class-b", "Class B", 1, 2.0, 0.7),
        )
    )

    assert decision.similarity_margin == pytest.approx(0.1)
    assert decision.state is SemanticClassDecisionState.KNOWN


def test_below_vote_threshold_is_uncertain():
    decision = _decide(_consensus(_candidate(top1_votes=3)))

    assert decision.state is SemanticClassDecisionState.UNCERTAIN
    assert decision.reasons == (SemanticClassDecisionReason.INSUFFICIENT_TOP1_VOTES,)


def test_below_known_similarity_but_above_unknown_is_uncertain():
    decision = _decide(_consensus(_candidate(mean_similarity=0.6)))

    assert decision.state is SemanticClassDecisionState.UNCERTAIN
    assert decision.reasons == (SemanticClassDecisionReason.BELOW_KNOWN_SIMILARITY,)


def test_insufficient_similarity_margin_is_uncertain():
    decision = _decide(
        _consensus(
            _candidate(mean_similarity=0.8),
            _candidate("class-b", "Class B", 1, 2.0, 0.71),
        )
    )

    assert decision.state is SemanticClassDecisionState.UNCERTAIN
    assert decision.reasons == (
        SemanticClassDecisionReason.INSUFFICIENT_SIMILARITY_MARGIN,
    )


def test_similarity_exactly_at_unknown_boundary_is_unknown():
    decision = _decide(_consensus(_candidate(mean_similarity=0.3)))

    assert decision.state is SemanticClassDecisionState.UNKNOWN


def test_similarity_below_unknown_boundary_is_unknown():
    decision = _decide(_consensus(_candidate(mean_similarity=0.2)))

    assert decision.state is SemanticClassDecisionState.UNKNOWN


def test_non_empty_unknown_decision_preserves_candidate_diagnostically():
    candidate = _candidate(mean_similarity=0.2)
    decision = _decide(_consensus(candidate))

    assert decision.candidate is candidate
    assert decision.reasons == (SemanticClassDecisionReason.BELOW_UNKNOWN_SIMILARITY,)


def test_one_strong_class_can_be_known_without_runner_up():
    candidate = _candidate(top1_votes=6, mean_similarity=0.9)
    decision = _decide(_consensus(candidate))

    assert decision.state is SemanticClassDecisionState.KNOWN
    assert decision.runner_up is None
    assert decision.similarity_margin is None


def test_one_weak_class_is_unknown():
    decision = _decide(_consensus(_candidate(top1_votes=6, mean_similarity=0.1)))

    assert decision.state is SemanticClassDecisionState.UNKNOWN


def test_one_middle_strength_class_is_uncertain():
    decision = _decide(_consensus(_candidate(top1_votes=6, mean_similarity=0.6)))

    assert decision.state is SemanticClassDecisionState.UNCERTAIN


def test_runner_up_is_second_consensus_class():
    first = _candidate(mean_similarity=0.9)
    second = _candidate("class-b", "Class B", 1, 2.0, 0.6)
    third = _candidate("class-c", "Class C", 0, 3.0, 0.2)

    decision = _decide(_consensus(first, second, third))

    assert decision.runner_up is second


def test_similarity_margin_is_top_minus_runner_up_mean_similarity():
    decision = _decide(
        _consensus(
            _candidate(mean_similarity=0.82),
            _candidate("class-b", "Class B", 1, 2.0, 0.57),
        )
    )

    assert decision.similarity_margin == pytest.approx(0.25)


def test_input_consensus_is_not_mutated():
    consensus = _consensus(
        _candidate(mean_similarity=0.82),
        _candidate("class-b", "Class B", 1, 2.0, 0.57),
    )
    before = consensus.classes

    _decide(consensus)

    assert consensus.classes == before


def test_decision_and_config_are_immutable():
    config = _config()
    decision = SemanticClassDecisionPolicy(config).decide(
        _consensus(_candidate(mean_similarity=0.9))
    )

    with pytest.raises(FrozenInstanceError):
        config.known_min_top1_votes = 1
    with pytest.raises(FrozenInstanceError):
        decision.state = SemanticClassDecisionState.UNKNOWN


@pytest.mark.parametrize("value", [0, 7, -1])
def test_vote_threshold_outside_one_through_six_is_rejected(value):
    with pytest.raises(ValueError, match="from 1 through 6"):
        _config(known_min_top1_votes=value)


def test_bool_vote_threshold_is_rejected():
    with pytest.raises(TypeError, match="integer from 1 through 6"):
        _config(known_min_top1_votes=True)


@pytest.mark.parametrize("value", [3.0, "3", None])
def test_non_integer_vote_threshold_is_rejected(value):
    with pytest.raises(TypeError, match="integer from 1 through 6"):
        _config(known_min_top1_votes=value)


@pytest.mark.parametrize(
    "name",
    [
        "known_min_mean_similarity",
        "known_min_similarity_margin",
        "unknown_max_mean_similarity",
    ],
)
@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_non_finite_threshold_is_rejected(name, value):
    with pytest.raises(ValueError, match=f"{name} must be finite"):
        _config(**{name: value})


@pytest.mark.parametrize(
    "name",
    [
        "known_min_mean_similarity",
        "known_min_similarity_margin",
        "unknown_max_mean_similarity",
    ],
)
@pytest.mark.parametrize("value", ["0.5", None, True])
def test_non_real_threshold_is_rejected(name, value):
    with pytest.raises(TypeError, match=f"{name} must be a real, finite value"):
        _config(**{name: value})


@pytest.mark.parametrize(
    "name",
    [
        "known_min_mean_similarity",
        "unknown_max_mean_similarity",
    ],
)
@pytest.mark.parametrize("value", [-1.01, 1.01])
def test_mean_similarity_threshold_outside_cosine_range_is_rejected(name, value):
    with pytest.raises(ValueError, match=rf"{name} must be within \[-1, 1\]"):
        _config(**{name: value})


@pytest.mark.parametrize("value", [-0.01, 2.01])
def test_margin_threshold_outside_zero_through_two_is_rejected(value):
    with pytest.raises(
        ValueError,
        match=r"known_min_similarity_margin must be within \[0, 2\]",
    ):
        _config(known_min_similarity_margin=value)


def test_unknown_threshold_cannot_exceed_known_threshold():
    with pytest.raises(
        ValueError,
        match="unknown_max_mean_similarity must be less than or equal",
    ):
        _config(
            known_min_mean_similarity=0.4,
            unknown_max_mean_similarity=0.5,
        )


def test_configuration_changes_decision_without_changing_consensus():
    consensus = _consensus(_candidate(top1_votes=4, mean_similarity=0.75))

    accepted = _decide(consensus)
    stricter = _decide(consensus, known_min_top1_votes=5)

    assert accepted.state is SemanticClassDecisionState.KNOWN
    assert stricter.state is SemanticClassDecisionState.UNCERTAIN
    assert accepted.candidate is stricter.candidate is consensus.classes[0]


def test_uncertain_reasons_are_ordered_and_can_preserve_multiple_failures():
    decision = _decide(
        _consensus(
            _candidate(top1_votes=3, mean_similarity=0.6),
            _candidate("class-b", "Class B", 3, 2.0, 0.55),
        )
    )

    assert decision.reasons == (
        SemanticClassDecisionReason.INSUFFICIENT_TOP1_VOTES,
        SemanticClassDecisionReason.BELOW_KNOWN_SIMILARITY,
        SemanticClassDecisionReason.INSUFFICIENT_SIMILARITY_MARGIN,
    )


def test_decision_exposes_no_probability_confidence_or_fused_score():
    decision = _decide(_consensus(_candidate(mean_similarity=0.9)))

    assert not hasattr(decision, "probability")
    assert not hasattr(decision, "confidence")
    assert not hasattr(decision, "weighted_score")
    assert not hasattr(decision, "final_fused_score")
