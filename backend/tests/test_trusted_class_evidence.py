"""Tests for trusted representation-specific centroid evidence updates."""

from dataclasses import FrozenInstanceError

import pytest
from services.semantic import (
    CandidateConfirmation,
    CandidateConfirmationSource,
    CandidateConfirmationState,
    CandidateIdentity,
    RepresentationEmbeddings,
    SemanticClassDecision,
    SemanticClassDecisionReason,
    SemanticClassDecisionState,
    TrustedClassEvidence,
    TrustedClassEvidenceStore,
    TrustedClassEvidenceUpdater,
    UnknownStreamEntry,
    UnknownStreamPool,
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
        SemanticClassDecisionState.UNKNOWN,
        None,
        None,
        None,
        (SemanticClassDecisionReason.NO_KNOWN_CLASSES,),
    )


def _embeddings(key_only, **overrides):
    values = {name: (99.0, 99.0) for name in VIEW_NAMES}
    values["key_only"] = key_only
    values.update(overrides)
    return RepresentationEmbeddings(**values)


def _entry(topic, key_only, **overrides):
    return UnknownStreamEntry(topic, _embeddings(key_only, **overrides), _decision())


def _pool(*entries):
    pool = UnknownStreamPool()
    for entry in entries:
        pool.upsert(entry)
    return pool


def _confirmation(
    topics,
    representation_name="key_only",
    semantic_class_name="Temperature",
    state=CandidateConfirmationState.CONFIRMED,
):
    return CandidateConfirmation(
        identity=CandidateIdentity(representation_name, topics),
        state=state,
        source=CandidateConfirmationSource.HUMAN,
        semantic_class_name=semantic_class_name
        if state is CandidateConfirmationState.CONFIRMED
        else None,
    )


def _apply(confirmation, pool, store=None):
    return TrustedClassEvidenceUpdater().apply_confirmation(
        confirmation,
        pool,
        store if store is not None else TrustedClassEvidenceStore(),
    )


def test_confirmed_key_only_candidate_creates_only_key_only_prototype():
    pool = _pool(_entry("topic/a", (1.0, 0.0)), _entry("topic/b", (3.0, 0.0)))
    store = TrustedClassEvidenceStore()

    evidence = _apply(_confirmation(("topic/b", "topic/a")), pool, store)

    assert evidence.representation_name == "key_only"
    assert evidence.centroid == pytest.approx((2.0, 0.0))
    assert evidence.member_topics == ("topic/a", "topic/b")
    assert evidence.member_count == 2
    assert store.get("Temperature", "key_only") is evidence
    assert all(
        store.get("Temperature", name) is None
        for name in VIEW_NAMES
        if name != "key_only"
    )


def test_only_confirmed_representation_embedding_is_used():
    pool = _pool(
        _entry("topic/a", (1.0, 0.0), schema=(1000.0, 1000.0)),
        _entry("topic/b", (3.0, 0.0), schema=(2000.0, 2000.0)),
    )

    evidence = _apply(_confirmation(("topic/a", "topic/b")), pool)

    assert evidence.centroid == pytest.approx((2.0, 0.0))
    assert not hasattr(evidence, "fused_vector")
    assert not hasattr(evidence, "representation_weights")


def test_same_semantic_class_in_two_views_remains_separate_evidence():
    pool = _pool(
        _entry("topic/a", (1.0, 0.0), schema=(10.0, 0.0)),
        _entry("topic/b", (3.0, 0.0), schema=(30.0, 0.0)),
    )
    store = TrustedClassEvidenceStore()

    key_evidence = _apply(_confirmation(("topic/a", "topic/b")), pool, store)
    schema_evidence = _apply(
        _confirmation(("topic/a", "topic/b"), "schema"), pool, store
    )

    assert key_evidence.centroid == pytest.approx((2.0, 0.0))
    assert schema_evidence.centroid == pytest.approx((20.0, 0.0))
    assert len(store) == 2


def test_incremental_new_topics_and_partial_overlap_are_count_weighted_and_idempotent():
    pool = _pool(
        _entry("topic/a", (1.0, 0.0)),
        _entry("topic/b", (3.0, 0.0)),
        _entry("topic/c", (8.0, 0.0)),
    )
    store = TrustedClassEvidenceStore()
    first = _apply(_confirmation(("topic/a", "topic/b")), pool, store)
    updated = _apply(_confirmation(("topic/b", "topic/c")), pool, store)
    replayed = _apply(_confirmation(("topic/b", "topic/c")), pool, store)

    assert first.centroid == pytest.approx((2.0, 0.0))
    assert updated.centroid == pytest.approx((4.0, 0.0))
    assert updated.member_topics == ("topic/a", "topic/b", "topic/c")
    assert updated.member_count == 3
    assert replayed is updated
    assert replayed.member_count == 3


def test_two_batches_match_centroid_of_all_unique_members():
    pool = _pool(
        _entry("topic/a", (1.0, 2.0)),
        _entry("topic/b", (3.0, 4.0)),
        _entry("topic/c", (8.0, 10.0)),
    )
    store = TrustedClassEvidenceStore()
    _apply(_confirmation(("topic/a", "topic/b")), pool, store)
    evidence = _apply(_confirmation(("topic/c",)), pool, store)

    assert evidence.centroid == pytest.approx((4.0, 16.0 / 3.0))


def test_missing_pool_topic_rejects_whole_update_without_partial_evidence():
    pool = _pool(_entry("topic/a", (1.0, 0.0)))
    store = TrustedClassEvidenceStore()

    with pytest.raises(ValueError, match="Missing UNKNOWN pool topics: topic/b"):
        _apply(_confirmation(("topic/a", "topic/b")), pool, store)

    assert len(store) == 0


def test_rejected_confirmation_cannot_update_evidence():
    pool = _pool(_entry("topic/a", (1.0, 0.0)))
    store = TrustedClassEvidenceStore()

    with pytest.raises(ValueError, match="Only CONFIRMED"):
        _apply(
            _confirmation(("topic/a",), state=CandidateConfirmationState.REJECTED),
            pool,
            store,
        )

    assert len(store) == 0


def test_invalid_vectors_have_representation_context():
    cases = [
        ((1.0,), (1.0, 2.0), "dimension mismatch"),
        ((), (), "must not be empty"),
        ((float("nan"), 0.0), (1.0, 0.0), "real, finite"),
        ((True, 0.0), (1.0, 0.0), "real, finite"),
    ]
    for first_vector, second_vector, message in cases:
        pool = _pool(_entry("topic/a", first_vector), _entry("topic/b", second_vector))
        with pytest.raises((TypeError, ValueError), match=f"{message}.*|.*{message}"):
            _apply(_confirmation(("topic/a", "topic/b")), pool)


def test_different_semantic_class_names_remain_separate_evidence():
    pool = _pool(_entry("topic/a", (1.0, 0.0)))
    store = TrustedClassEvidenceStore()

    first = _apply(
        _confirmation(("topic/a",), semantic_class_name="Temperature"), pool, store
    )
    second = _apply(
        _confirmation(("topic/a",), semantic_class_name="Pressure"), pool, store
    )

    assert first is not second
    assert len(store) == 2


def test_store_operations_are_deterministic_and_immutable():
    first = TrustedClassEvidence("Zeta", "schema", (1.0,), ("topic/z",))
    second = TrustedClassEvidence("Alpha", "key_only", (2.0,), ("topic/a",))
    store = TrustedClassEvidenceStore()
    store.upsert(first)
    store.upsert(second)

    records = store.all()
    assert [
        (record.semantic_class_name, record.representation_name) for record in records
    ] == [("Alpha", "key_only"), ("Zeta", "schema")]
    assert isinstance(records, tuple)
    assert store.get("Alpha", "key_only") is second
    assert store.remove("Zeta", "schema") is first
    assert store.remove("Zeta", "schema") is None
    with pytest.raises(AttributeError):
        records.append(first)
    with pytest.raises(FrozenInstanceError):
        second.member_topics = ()


def test_confirmation_and_unknown_pool_are_not_mutated():
    entry = _entry("topic/a", (1.0, 0.0))
    pool = _pool(entry)
    confirmation = _confirmation(("topic/a",))

    _apply(confirmation, pool)

    assert pool.get("topic/a") is entry
    assert confirmation.identity.member_topics == ("topic/a",)


def test_partial_evidence_does_not_materialize_full_six_view_centroids():
    pool = _pool(_entry("topic/a", (1.0, 0.0)))
    evidence = _apply(_confirmation(("topic/a",)), pool)

    assert evidence.prototype.member_count == 1
    with pytest.raises(FrozenInstanceError):
        evidence.prototype.member_count = 2
    assert not hasattr(evidence, "centroids")
    assert not hasattr(evidence, "class_id")
