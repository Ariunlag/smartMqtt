import math
from dataclasses import FrozenInstanceError

import pytest
from services.semantic import (
    CandidateConfirmationSource,
    CandidateIdentity,
    CandidateMembershipReview,
    RepresentationEmbeddings,
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


def _pool(**topic_seeds):
    pool = UnknownStreamPool()
    for topic, seed in topic_seeds.items():
        pool.upsert(UnknownStreamEntry(topic, _embeddings(seed), _decision()))
    return pool


def _review(
    kept=("topic/a",),
    removed=("topic/b",),
    added=("topic/c",),
    class_name="Temperature",
):
    return CandidateMembershipReview(
        CandidateIdentity("key_only", tuple(sorted(kept + removed))),
        class_name,
        kept,
        removed,
        added,
        CandidateConfirmationSource.HUMAN,
    )


def test_positive_topics_create_six_matching_independent_prototypes():
    pool = _pool(**{"topic/a": 1.0, "topic/c": 3.0})
    review = _review()
    store = TrustedClassEvidenceStore()

    result = ReviewedPrototypeUpdater().apply(review, pool, store)

    assert result.semantic_class_name == "Temperature"
    assert result.positive_topics == ("topic/a", "topic/c")
    assert tuple(item.representation_name for item in result.evidence) == VIEWS
    assert result.changed_representations == VIEWS
    for index, evidence in enumerate(result.evidence, start=1):
        assert evidence.member_topics == ("topic/a", "topic/c")
        assert evidence.centroid == pytest.approx((2.0 * index, 2.0 * index + 0.5))
        assert store.get("Temperature", evidence.representation_name) is evidence
    assert all("topic/b" not in item.member_topics for item in result.evidence)
    assert pool.get("topic/a").embeddings.value_only == (1.0, 1.5)
    assert review == _review()


def test_replay_is_idempotent_and_returns_no_changed_views():
    pool = _pool(**{"topic/a": 1.0, "topic/c": 3.0})
    store = TrustedClassEvidenceStore()
    updater = ReviewedPrototypeUpdater()
    first = updater.apply(_review(), pool, store)
    before = store.all()

    replay = updater.apply(_review(), pool, store)

    assert replay.changed_representations == ()
    assert replay.evidence == first.evidence
    assert store.all() == before
    assert all(left is right for left, right in zip(store.all(), before, strict=True))
    assert all(item.member_count == 2 for item in replay.evidence)


def test_partial_overlap_adds_only_new_topics_with_count_weighted_centroids():
    pool = _pool(**{"topic/a": 1.0, "topic/c": 3.0, "topic/d": 5.0})
    store = TrustedClassEvidenceStore()
    updater = ReviewedPrototypeUpdater()
    updater.apply(_review(), pool, store)
    review = CandidateMembershipReview(
        CandidateIdentity("schema", ("topic/a", "topic/d")),
        "Temperature",
        ("topic/a", "topic/d"),
        (),
        (),
        CandidateConfirmationSource.HUMAN,
    )

    result = updater.apply(review, pool, store)

    assert result.changed_representations == VIEWS
    for index, evidence in enumerate(result.evidence, start=1):
        assert evidence.member_topics == ("topic/a", "topic/c", "topic/d")
        assert evidence.centroid == pytest.approx((3.0 * index, 3.0 * index + 0.5))


def test_same_positive_topics_update_another_class_independently():
    pool = _pool(**{"topic/a": 1.0, "topic/c": 3.0})
    store = TrustedClassEvidenceStore()
    updater = ReviewedPrototypeUpdater()
    first = updater.apply(_review(), pool, store)

    other = updater.apply(_review(class_name="Air Quality"), pool, store)

    assert len(store) == 12
    assert other.evidence[0] is not first.evidence[0]
    assert other.evidence[0].centroid == first.evidence[0].centroid


def test_missing_positive_topic_is_atomic_and_removed_topic_need_not_exist():
    pool = _pool(**{"topic/a": 1.0, "topic/c": 3.0})
    store = TrustedClassEvidenceStore()
    updater = ReviewedPrototypeUpdater()
    updater.apply(_review(), pool, store)
    before = store.all()
    missing_review = _review(
        kept=("topic/a",), removed=("topic/b",), added=("topic/missing",)
    )

    with pytest.raises(ValueError, match="topic/missing"):
        updater.apply(missing_review, pool, store)

    assert store.all() == before
    assert len(pool) == 2


@pytest.mark.parametrize(
    "invalid", ((), (math.nan, 1.0), (math.inf, 1.0), (-math.inf, 1.0), (True, 1.0))
)
def test_invalid_sixth_view_vector_rejects_all_views_atomically(invalid):
    pool = _pool(**{"topic/a": 1.0, "topic/c": 3.0})
    store = TrustedClassEvidenceStore()
    updater = ReviewedPrototypeUpdater()
    updater.apply(_review(), pool, store)
    before = store.all()
    bad = UnknownStreamEntry(
        "topic/d",
        _embeddings(5.0, topic_key_value=invalid),
        _decision(),
    )
    pool.upsert(bad)
    review = CandidateMembershipReview(
        CandidateIdentity("value_only", ("topic/d",)),
        "Temperature",
        ("topic/d",),
        (),
        (),
        CandidateConfirmationSource.HUMAN,
    )

    with pytest.raises((TypeError, ValueError), match="topic_key_value"):
        updater.apply(review, pool, store)

    assert store.all() == before
    assert all(left is right for left, right in zip(store.all(), before, strict=True))


def test_dimension_mismatch_and_incompatible_existing_prototype_are_atomic():
    pool = _pool(**{"topic/a": 1.0, "topic/c": 3.0})
    mismatched = UnknownStreamEntry(
        "topic/d",
        _embeddings(5.0, schema=(1.0, 2.0, 3.0)),
        _decision(),
    )
    pool.upsert(mismatched)
    store = TrustedClassEvidenceStore()
    store.upsert(TrustedClassEvidence("Temperature", "schema", (1.0, 2.0), ("old",)))
    before = store.all()
    review = CandidateMembershipReview(
        CandidateIdentity("key_only", ("topic/d",)),
        "Temperature",
        ("topic/d",),
        (),
        (),
        CandidateConfirmationSource.HUMAN,
    )

    with pytest.raises(ValueError, match="schema"):
        ReviewedPrototypeUpdater().apply(review, pool, store)

    assert store.all() == before
    assert len(store) == 1


def test_result_is_immutable_and_has_no_assembled_or_scored_fields():
    result = ReviewedPrototypeUpdater().apply(
        _review(),
        _pool(**{"topic/a": 1.0, "topic/c": 3.0}),
        TrustedClassEvidenceStore(),
    )

    with pytest.raises(FrozenInstanceError):
        result.semantic_class_name = "Other"
    forbidden = {
        "class_id",
        "centroids",
        "similarity",
        "score",
        "weight",
        "reliability",
    }
    assert forbidden.isdisjoint(result.__dataclass_fields__)
