import math
from dataclasses import FrozenInstanceError

import pytest
from services.semantic import (
    CandidateConfirmationSource,
    CandidateIdentity,
    CandidateMembershipReview,
    RepresentationEmbeddings,
    ReviewedPrototypeReconciler,
    ReviewedPrototypeUpdater,
    SemanticClassDecision,
    SemanticClassDecisionReason,
    SemanticClassDecisionState,
    TrustedClassEvidence,
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


def _pool(seeds=None, overrides=None):
    pool = UnknownStreamPool()
    for topic, seed in (
        seeds or {"A": 1.0, "B": 2.0, "C": 3.0, "D": 4.0, "E": 5.0}
    ).items():
        pool.upsert(
            UnknownStreamEntry(
                topic,
                _embeddings(seed, **((overrides or {}).get(topic, {}))),
                _decision(),
            )
        )
    return pool


def _positive_review(topics, class_name="Class A"):
    return CandidateMembershipReview(
        CandidateIdentity("schema", topics),
        class_name,
        topics,
        (),
        (),
        CandidateConfirmationSource.HUMAN,
    )


def _correction(class_name="Class A"):
    return CandidateMembershipReview(
        CandidateIdentity("key_only", ("A", "B", "C", "D")),
        class_name,
        ("B", "A"),
        ("D", "C"),
        ("E",),
        CandidateConfirmationSource.HUMAN,
    )


def _seed(pool, class_name="Class A"):
    store = TrustedClassEvidenceStore()
    ReviewedPrototypeUpdater().apply(
        _positive_review(("A", "B", "C", "D"), class_name),
        pool,
        store,
    )
    return store


def test_reconciliation_rebuilds_all_views_from_final_unique_members():
    pool = _pool()
    store = _seed(pool)

    result = ReviewedPrototypeReconciler().apply(_correction(), pool, store)

    assert result.positive_topics == ("A", "B", "E")
    assert result.removed_topics == ("C", "D")
    assert result.changed_representations == VIEWS
    assert tuple(item.representation_name for item in result.evidence) == VIEWS
    for index, evidence in enumerate(result.evidence, start=1):
        assert evidence.member_topics == ("A", "B", "E")
        assert evidence.centroid == pytest.approx(
            (8.0 / 3 * index, 8.0 / 3 * index + 0.5)
        )
    assert len(pool) == 5


def test_unrelated_existing_member_remains_and_current_embeddings_are_used():
    pool = _pool({"A": 1.0, "B": 2.0, "C": 3.0, "D": 4.0, "E": 5.0, "F": 6.0})
    store = _seed(pool)
    ReviewedPrototypeUpdater().apply(_positive_review(("F",)), pool, store)
    pool.upsert(UnknownStreamEntry("A", _embeddings(10.0), _decision()))

    result = ReviewedPrototypeReconciler().apply(_correction(), pool, store)

    assert all(item.member_topics == ("A", "B", "E", "F") for item in result.evidence)
    assert result.evidence[0].centroid == pytest.approx((23.0 / 4, 23.0 / 4 + 0.5))


def test_replay_is_idempotent_and_preserves_existing_objects():
    pool = _pool()
    store = _seed(pool)
    reconciler = ReviewedPrototypeReconciler()
    first = reconciler.apply(_correction(), pool, store)
    before = store.all()

    replay = reconciler.apply(_correction(), pool, store)

    assert replay.changed_representations == ()
    assert replay.evidence == first.evidence
    assert store.all() == before
    assert all(left is right for left, right in zip(store.all(), before, strict=True))


def test_only_views_with_changed_membership_are_rebuilt():
    pool = _pool()
    store = _seed(pool)
    existing_schema = TrustedClassEvidence(
        "Class A",
        "schema",
        (999.0, 999.0),
        ("A", "B", "E"),
    )
    store.upsert(existing_schema)

    result = ReviewedPrototypeReconciler().apply(_correction(), pool, store)

    assert "schema" not in result.changed_representations
    assert result.evidence[3] is existing_schema
    assert len(result.changed_representations) == 5


def test_missing_prototypes_are_created_and_positive_only_matches_updater():
    pool = _pool({"A": 1.0, "E": 5.0})
    review = _positive_review(("A", "E"))
    reconciled_store = TrustedClassEvidenceStore()
    updated_store = TrustedClassEvidenceStore()

    reconciled = ReviewedPrototypeReconciler().apply(review, pool, reconciled_store)
    updated = ReviewedPrototypeUpdater().apply(review, pool, updated_store)

    assert reconciled.changed_representations == VIEWS
    assert reconciled.evidence == updated.evidence


def test_missing_remaining_member_is_atomic_but_removed_members_need_not_exist():
    pool = _pool()
    store = _seed(pool)
    ReviewedPrototypeUpdater().apply(_positive_review(("F",)), _pool({"F": 6.0}), store)
    before = store.all()

    with pytest.raises(ValueError, match="F"):
        ReviewedPrototypeReconciler().apply(_correction(), pool, store)

    assert store.all() == before
    assert all(left is right for left, right in zip(store.all(), before, strict=True))


@pytest.mark.parametrize(
    "invalid", ((), (math.nan, 1.0), (math.inf, 1.0), (-math.inf, 1.0), (True, 1.0))
)
def test_invalid_sixth_view_rejects_first_five_atomically(invalid):
    pool = _pool(overrides={"E": {"topic_key_value": invalid}})
    store = _seed(pool)
    before = store.all()

    with pytest.raises((TypeError, ValueError), match="topic_key_value"):
        ReviewedPrototypeReconciler().apply(_correction(), pool, store)

    assert store.all() == before
    assert all(left is right for left, right in zip(store.all(), before, strict=True))


def test_dimension_mismatch_is_atomic():
    pool = _pool(overrides={"E": {"schema": (1.0, 2.0, 3.0)}})
    store = _seed(pool)
    before = store.all()

    with pytest.raises(ValueError, match="schema"):
        ReviewedPrototypeReconciler().apply(_correction(), pool, store)

    assert store.all() == before


def test_same_review_reconciles_another_class_and_result_is_immutable():
    pool = _pool()
    store = _seed(pool)
    other_store = _seed(pool, "Class B")
    for item in other_store.all():
        store.upsert(item)

    result = ReviewedPrototypeReconciler().apply(_correction("Class B"), pool, store)

    assert len(store) == 12
    assert result.semantic_class_name == "Class B"
    with pytest.raises(FrozenInstanceError):
        result.removed_topics = ()
    forbidden = {"similarity", "score", "weight", "reliability", "class_id"}
    assert forbidden.isdisjoint(result.__dataclass_fields__)
