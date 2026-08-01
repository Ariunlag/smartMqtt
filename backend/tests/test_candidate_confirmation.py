"""Tests for explicit confirmation and rejection of discovery candidates."""

from dataclasses import FrozenInstanceError

import pytest
from services.semantic import (
    CandidateConfirmation,
    CandidateConfirmationSource,
    CandidateConfirmationState,
    CandidateConfirmationStore,
    CandidateIdentity,
    UnknownClusterCandidate,
)


def _identity(representation_name="schema", topics=("topic/a", "topic/b")):
    return CandidateIdentity(representation_name, topics)


def _confirmation(
    identity=None,
    state=CandidateConfirmationState.CONFIRMED,
    source=CandidateConfirmationSource.HUMAN,
    semantic_class_name="Environment",
):
    if state is CandidateConfirmationState.REJECTED:
        semantic_class_name = None
    return CandidateConfirmation(
        identity=identity or _identity(),
        state=state,
        source=source,
        semantic_class_name=semantic_class_name,
    )


def test_identity_is_created_from_candidate_without_candidate_index():
    first = UnknownClusterCandidate("schema", 0, ("topic/b", "topic/a"))
    second = UnknownClusterCandidate("schema", 99, ("topic/a", "topic/b"))

    assert CandidateIdentity.from_candidate(first) == CandidateIdentity.from_candidate(
        second
    )
    assert CandidateIdentity.from_candidate(first).member_topics == (
        "topic/a",
        "topic/b",
    )


def test_same_members_in_different_representations_are_distinct_identities():
    key_identity = _identity("key_only")
    schema_identity = _identity("schema")

    assert key_identity != schema_identity


@pytest.mark.parametrize("topics", [(), ("topic/a", "topic/a")])
def test_empty_or_duplicate_member_topics_are_rejected(topics):
    with pytest.raises(ValueError, match="member_topics"):
        _identity(topics=topics)


@pytest.mark.parametrize("representation_name", ["", "unknown", "KEY_ONLY"])
def test_invalid_representation_name_is_rejected(representation_name):
    with pytest.raises(ValueError, match="representation_name"):
        _identity(representation_name=representation_name)


@pytest.mark.parametrize("topics", [("",), ("   ",), (None,), (1,), (True,)])
def test_invalid_member_topic_is_rejected(topics):
    with pytest.raises(
        ValueError, match="member_topics must contain non-empty strings"
    ):
        _identity(topics=topics)


@pytest.mark.parametrize("semantic_class_name", [None, "", "   "])
def test_confirmed_requires_non_empty_semantic_class_name(semantic_class_name):
    with pytest.raises(ValueError, match="semantic_class_name must be a non-empty"):
        CandidateConfirmation(
            _identity(),
            CandidateConfirmationState.CONFIRMED,
            CandidateConfirmationSource.HUMAN,
            semantic_class_name,
        )


def test_rejected_requires_no_semantic_class_name():
    with pytest.raises(ValueError, match="semantic_class_name must be None"):
        CandidateConfirmation(
            _identity(),
            CandidateConfirmationState.REJECTED,
            CandidateConfirmationSource.HUMAN,
            "Environment",
        )


@pytest.mark.parametrize(
    "source",
    [CandidateConfirmationSource.HUMAN, CandidateConfirmationSource.SYSTEM],
)
def test_human_and_system_confirmations_are_explicitly_accepted(source):
    confirmation = _confirmation(source=source)

    assert confirmation.source is source
    assert confirmation.state is CandidateConfirmationState.CONFIRMED


def test_store_record_and_get_work():
    store = CandidateConfirmationStore()
    confirmation = _confirmation()

    store.record(confirmation)

    assert store.get(confirmation.identity) is confirmation


def test_record_replaces_same_identity_without_increasing_size():
    store = CandidateConfirmationStore()
    identity = _identity()
    rejected = _confirmation(identity, CandidateConfirmationState.REJECTED)
    confirmed = _confirmation(identity, CandidateConfirmationState.CONFIRMED)
    store.record(rejected)
    store.record(confirmed)

    assert len(store) == 1
    assert store.get(identity) is confirmed


def test_confirmed_and_rejected_records_can_replace_each_other():
    store = CandidateConfirmationStore()
    identity = _identity()
    confirmed = _confirmation(identity)
    rejected = _confirmation(identity, CandidateConfirmationState.REJECTED)

    store.record(confirmed)
    store.record(rejected)
    assert store.get(identity) is rejected
    store.record(confirmed)
    assert store.get(identity) is confirmed


def test_remove_returns_confirmation_and_missing_returns_none():
    store = CandidateConfirmationStore()
    confirmation = _confirmation()
    store.record(confirmation)

    assert store.remove(confirmation.identity) is confirmation
    assert store.remove(confirmation.identity) is None


def test_all_returns_immutable_tuple_in_deterministic_identity_order():
    store = CandidateConfirmationStore()
    confirmations = (
        _confirmation(_identity("schema", ("topic/z",))),
        _confirmation(_identity("key_only", ("topic/z",))),
        _confirmation(_identity("schema", ("topic/a",))),
    )
    for confirmation in confirmations:
        store.record(confirmation)

    records = store.all()

    assert isinstance(records, tuple)
    assert [
        (record.identity.representation_name, record.identity.member_topics)
        for record in records
    ] == [
        ("key_only", ("topic/z",)),
        ("schema", ("topic/a",)),
        ("schema", ("topic/z",)),
    ]
    with pytest.raises(AttributeError):
        records.append(_confirmation())


def test_insertion_order_does_not_change_store_output():
    first = _confirmation(_identity("schema", ("topic/b",)))
    second = _confirmation(_identity("key_only", ("topic/a",)))
    forward = CandidateConfirmationStore()
    reverse = CandidateConfirmationStore()
    forward.record(first)
    forward.record(second)
    reverse.record(second)
    reverse.record(first)

    assert forward.all() == reverse.all()


def test_domain_models_are_immutable_and_candidate_is_not_mutated():
    candidate = UnknownClusterCandidate("schema", 3, ("topic/b", "topic/a"))
    identity = CandidateIdentity.from_candidate(candidate)
    confirmation = _confirmation(identity)

    with pytest.raises(FrozenInstanceError):
        identity.member_topics = ()
    with pytest.raises(FrozenInstanceError):
        confirmation.state = CandidateConfirmationState.REJECTED
    assert candidate.candidate_index == 3
    assert candidate.member_topics == ("topic/b", "topic/a")


def test_confirmation_has_no_automatic_or_class_update_fields():
    confirmation = _confirmation()

    assert not hasattr(confirmation, "cluster_size")
    assert not hasattr(confirmation, "probability")
    assert not hasattr(confirmation, "class_id")
    assert not hasattr(confirmation, "centroid")
    assert not hasattr(confirmation, "update")


def test_confirmation_store_does_not_mutate_records():
    store = CandidateConfirmationStore()
    confirmation = _confirmation()
    store.record(confirmation)

    assert store.get(confirmation.identity) is confirmation
    assert store.all()[0] is confirmation


@pytest.mark.parametrize("state", ["CONFIRMED", None])
def test_invalid_confirmation_state_is_rejected(state):
    with pytest.raises(TypeError, match="state must be a CandidateConfirmationState"):
        CandidateConfirmation(
            _identity(),
            state,
            CandidateConfirmationSource.HUMAN,
            "Environment",
        )


@pytest.mark.parametrize("source", ["HUMAN", None])
def test_invalid_confirmation_source_is_rejected(source):
    with pytest.raises(TypeError, match="source must be a CandidateConfirmationSource"):
        CandidateConfirmation(
            _identity(),
            CandidateConfirmationState.CONFIRMED,
            source,
            "Environment",
        )
