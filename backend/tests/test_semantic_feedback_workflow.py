import math
from dataclasses import FrozenInstanceError

import pytest
from services.semantic import (
    CandidateConfirmationSource,
    CandidateIdentity,
    CandidateMembershipReview,
    NegativeMembershipConstraint,
    NegativeMembershipConstraintStore,
    RepresentationClassConsensus,
    RepresentationEmbeddings,
    ReviewedPrototypeUpdater,
    SemanticClassDecision,
    SemanticClassDecisionReason,
    SemanticClassDecisionState,
    SemanticFeedbackWorkflow,
    TrustedClassEvidenceStore,
    UnknownStreamEntry,
    UnknownStreamPool,
)

VIEWS = (
    "value_only",
    "key_only",
    "key_value",
    "schema",
    "numeric_key_only",
    "topic_key_value",
)


def _decision():
    return SemanticClassDecision(
        SemanticClassDecisionState.UNKNOWN,
        None,
        None,
        None,
        (SemanticClassDecisionReason.NO_KNOWN_CLASSES,),
    )


def _embeddings(seed, **overrides):
    values = {
        name: (seed * (index + 1), seed * (index + 1) + 0.5)
        for index, name in enumerate(VIEWS)
    }
    values.update(overrides)
    return RepresentationEmbeddings(**values)


def _pool(overrides=None):
    pool = UnknownStreamPool()
    for topic, seed in {"A": 1.0, "B": 2.0, "C": 3.0, "D": 4.0}.items():
        pool.upsert(
            UnknownStreamEntry(
                topic,
                _embeddings(seed, **((overrides or {}).get(topic, {}))),
                _decision(),
            )
        )
    return pool


def _review(class_name="Class A"):
    return CandidateMembershipReview(
        CandidateIdentity("key_only", ("A", "B", "C")),
        class_name,
        ("A", "B"),
        ("C",),
        ("D",),
        CandidateConfirmationSource.HUMAN,
    )


def _positive_review(topics, class_name="Class A"):
    return CandidateMembershipReview(
        CandidateIdentity("schema", topics),
        class_name,
        topics,
        (),
        (),
        CandidateConfirmationSource.HUMAN,
    )


def _seed(pool):
    store = TrustedClassEvidenceStore()
    ReviewedPrototypeUpdater().apply(
        _positive_review(("A", "B", "C")),
        pool,
        store,
    )
    return store


def test_workflow_reconciles_prototypes_and_adds_only_removed_constraint():
    pool = _pool()
    evidence_store = _seed(pool)
    constraints = NegativeMembershipConstraintStore()
    review = _review()
    pool_before = pool.all()

    result = SemanticFeedbackWorkflow().apply_review(
        review,
        pool,
        evidence_store,
        constraints,
    )

    assert result.changed_representations == VIEWS
    assert result.positive_topics == ("A", "B", "D")
    assert result.removed_topics == ("C",)
    assert result.constraints_added == (NegativeMembershipConstraint("C", "Class A"),)
    assert result.constraints_removed == ()
    assert constraints.is_blocked("C", "Class A")
    assert not constraints.is_blocked("A", "Class A")
    assert not constraints.is_blocked("D", "Class A")
    assert all(
        item.member_topics == ("A", "B", "D") for item in result.prototype_evidence
    )
    assert pool.all() == pool_before
    assert review == _review()


def test_positive_feedback_clears_matching_constraint_only():
    pool = _pool()
    evidence_store = _seed(pool)
    constraints = NegativeMembershipConstraintStore()
    constraints.upsert(NegativeMembershipConstraint("C", "Class A"))
    constraints.upsert(NegativeMembershipConstraint("C", "Class B"))

    result = SemanticFeedbackWorkflow().apply_review(
        _positive_review(("C",)),
        pool,
        evidence_store,
        constraints,
    )

    assert result.constraints_removed == (NegativeMembershipConstraint("C", "Class A"),)
    assert not constraints.is_blocked("C", "Class A")
    assert constraints.is_blocked("C", "Class B")


def test_repeated_negative_feedback_is_idempotent():
    pool = _pool()
    evidence_store = _seed(pool)
    constraints = NegativeMembershipConstraintStore()
    workflow = SemanticFeedbackWorkflow()
    workflow.apply_review(_review(), pool, evidence_store, constraints)
    size = len(constraints)

    replay = workflow.apply_review(_review(), pool, evidence_store, constraints)

    assert len(constraints) == size
    assert replay.constraints_added == ()
    assert replay.constraints_removed == ()
    assert replay.changed_representations == ()


def test_constraint_filter_preserves_candidate_objects_order_and_scores():
    constraints = NegativeMembershipConstraintStore()
    constraints.upsert(NegativeMembershipConstraint("topic/x", "Class B"))
    candidates = (
        RepresentationClassConsensus("a", "Class A", 4, 1.2, 0.8),
        RepresentationClassConsensus("b", "Class B", 5, 1.0, 0.9),
        RepresentationClassConsensus("c", "Class C", 3, 1.5, 0.7),
    )

    allowed = constraints.filter_allowed("topic/x", candidates)

    assert allowed == (candidates[0], candidates[2])
    assert allowed[0] is candidates[0]
    assert candidates[1].mean_similarity == 0.9
    constraints.upsert(NegativeMembershipConstraint("topic/x", "Class A"))
    constraints.upsert(NegativeMembershipConstraint("topic/x", "Class C"))
    assert constraints.filter_allowed("topic/x", candidates) == ()


def test_constraint_store_is_class_wide_deterministic_and_removable():
    store = NegativeMembershipConstraintStore()
    first = NegativeMembershipConstraint("z", "Class A")
    store.upsert(first)
    store.upsert(NegativeMembershipConstraint("a", "Class B"))
    store.upsert(NegativeMembershipConstraint("z", "Class A"))

    assert len(store) == 2
    assert store.all() == (
        NegativeMembershipConstraint("z", "Class A"),
        NegativeMembershipConstraint("a", "Class B"),
    )
    assert store.remove("z", "Class A") == first


def test_missing_positive_topic_fails_before_either_store_changes():
    pool = _pool()
    evidence_store = _seed(pool)
    constraints = NegativeMembershipConstraintStore()
    constraints.upsert(NegativeMembershipConstraint("old", "Class A"))
    evidence_before = evidence_store.all()
    constraints_before = constraints.all()
    review = _positive_review(("missing",))

    with pytest.raises(ValueError, match="missing"):
        SemanticFeedbackWorkflow().apply_review(
            review,
            pool,
            evidence_store,
            constraints,
        )

    assert evidence_store.all() == evidence_before
    assert constraints.all() == constraints_before


@pytest.mark.parametrize("invalid", ((), (math.nan, 1.0), (math.inf, 1.0), (True, 1.0)))
def test_vector_failure_is_atomic_across_prototypes_and_constraints(invalid):
    pool = _pool(overrides={"D": {"topic_key_value": invalid}})
    evidence_store = _seed(pool)
    constraints = NegativeMembershipConstraintStore()
    constraints.upsert(NegativeMembershipConstraint("A", "Class A"))
    evidence_before = evidence_store.all()
    constraints_before = constraints.all()

    with pytest.raises((TypeError, ValueError), match="topic_key_value"):
        SemanticFeedbackWorkflow().apply_review(
            _review(),
            pool,
            evidence_store,
            constraints,
        )

    assert evidence_store.all() == evidence_before
    assert constraints.all() == constraints_before


def test_models_are_immutable_and_expose_no_adjustment_fields():
    constraint = NegativeMembershipConstraint("topic", "Class A")
    result = SemanticFeedbackWorkflow().apply_review(
        _review(),
        _pool(),
        _seed(_pool()),
        NegativeMembershipConstraintStore(),
    )

    with pytest.raises(FrozenInstanceError):
        constraint.topic = "other"
    with pytest.raises(FrozenInstanceError):
        result.removed_topics = ()
    forbidden = {"similarity", "score", "weight", "reliability", "reward"}
    assert forbidden.isdisjoint(constraint.__dataclass_fields__)
    assert forbidden.isdisjoint(result.__dataclass_fields__)
