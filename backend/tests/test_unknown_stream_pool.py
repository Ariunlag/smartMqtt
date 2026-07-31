"""Tests for the in-memory UNKNOWN stream evidence pool."""

from dataclasses import FrozenInstanceError

import pytest
from services.semantic import (
    RepresentationClassConsensus,
    RepresentationEmbeddings,
    SemanticClassDecision,
    SemanticClassDecisionReason,
    SemanticClassDecisionState,
    UnknownStreamEntry,
    UnknownStreamPool,
)


def _embeddings(seed=1.0):
    return RepresentationEmbeddings(
        value_only=(seed, 0.0),
        key_only=(0.0, seed),
        key_value=(seed, seed),
        schema=(seed, -seed),
        numeric_key_only=(-seed, seed),
        topic_key_value=(-seed, -seed),
    )


def _candidate():
    return RepresentationClassConsensus("class-a", "Class A", 1, 1.0, 0.2)


def _decision(state=SemanticClassDecisionState.UNKNOWN, candidate=None):
    return SemanticClassDecision(
        state=state,
        candidate=candidate,
        runner_up=None,
        similarity_margin=None,
        reasons=(SemanticClassDecisionReason.BELOW_UNKNOWN_SIMILARITY,),
    )


def _entry(topic="building/room-a", seed=1.0, decision=None):
    return UnknownStreamEntry(
        topic=topic,
        embeddings=_embeddings(seed),
        decision=decision or _decision(),
    )


def test_unknown_entry_can_be_inserted_and_retrieved():
    pool = UnknownStreamPool()
    entry = _entry()

    pool.upsert(entry)

    assert pool.get(entry.topic) is entry


def test_all_returns_an_immutable_tuple():
    pool = UnknownStreamPool()
    pool.upsert(_entry())

    entries = pool.all()

    assert isinstance(entries, tuple)
    with pytest.raises(AttributeError):
        entries.append(_entry("other"))


def test_all_sorts_topics_regardless_of_insertion_order():
    pool = UnknownStreamPool()
    pool.upsert(_entry("z/topic"))
    pool.upsert(_entry("a/topic"))
    pool.upsert(_entry("m/topic"))

    assert [entry.topic for entry in pool.all()] == ["a/topic", "m/topic", "z/topic"]


def test_pool_length_reflects_unique_topics():
    pool = UnknownStreamPool()
    pool.upsert(_entry("a/topic"))
    pool.upsert(_entry("b/topic"))

    assert len(pool) == 2


def test_repeated_upsert_replaces_entry_without_increasing_size():
    pool = UnknownStreamPool()
    first = _entry("a/topic", seed=1.0)
    latest = _entry("a/topic", seed=2.0, decision=_decision(candidate=_candidate()))
    pool.upsert(first)
    pool.upsert(latest)

    assert len(pool) == 1
    assert pool.get("a/topic") is latest
    assert pool.get("a/topic").embeddings == _embeddings(2.0)
    assert pool.get("a/topic").decision is latest.decision


def test_remove_returns_entry_and_makes_topic_unavailable():
    pool = UnknownStreamPool()
    entry = _entry()
    pool.upsert(entry)

    assert pool.remove(entry.topic) is entry
    assert pool.get(entry.topic) is None
    assert len(pool) == 0


def test_remove_missing_topic_returns_none_and_empty_pool_returns_empty_tuple():
    pool = UnknownStreamPool()

    assert pool.remove("missing") is None
    assert pool.all() == ()


@pytest.mark.parametrize("topic", ["", "   ", None, 1, True])
def test_invalid_topic_is_rejected(topic):
    with pytest.raises(ValueError, match="topic must be a non-empty string"):
        _entry(topic=topic)


@pytest.mark.parametrize(
    "state",
    [SemanticClassDecisionState.KNOWN, SemanticClassDecisionState.UNCERTAIN],
)
def test_known_and_uncertain_decisions_are_rejected(state):
    with pytest.raises(ValueError, match="requires an UNKNOWN decision"):
        _entry(decision=_decision(state=state))


def test_unknown_decision_with_diagnostic_candidate_is_accepted():
    entry = _entry(decision=_decision(candidate=_candidate()))

    assert entry.decision.candidate == _candidate()


def test_entry_is_immutable_and_pool_does_not_mutate_input_entry():
    entry = _entry()
    pool = UnknownStreamPool()
    pool.upsert(entry)

    with pytest.raises(FrozenInstanceError):
        entry.topic = "changed"
    assert pool.get(entry.topic) is entry


def test_returned_entries_cannot_mutate_pool_internals():
    pool = UnknownStreamPool()
    entry = _entry()
    pool.upsert(entry)
    returned = pool.all()[0]

    with pytest.raises(FrozenInstanceError):
        returned.decision = _decision()
    assert pool.get(entry.topic) is entry


def test_all_six_embeddings_are_preserved_exactly_without_transformation():
    entry = _entry(seed=3.0)
    pool = UnknownStreamPool()
    pool.upsert(entry)

    retained = pool.get(entry.topic)

    assert retained.embeddings is entry.embeddings
    assert retained.embeddings.as_dict() == {
        "value_only": (3.0, 0.0),
        "key_only": (0.0, 3.0),
        "key_value": (3.0, 3.0),
        "schema": (3.0, -3.0),
        "numeric_key_only": (-3.0, 3.0),
        "topic_key_value": (-3.0, -3.0),
    }


def test_upsert_does_not_aggregate_or_merge_embeddings_or_decisions():
    pool = UnknownStreamPool()
    first = _entry("a/topic", seed=1.0)
    second = _entry("a/topic", seed=4.0, decision=_decision(candidate=_candidate()))
    pool.upsert(first)
    pool.upsert(second)

    retained = pool.get("a/topic")

    assert retained is second
    assert retained.embeddings is second.embeddings
    assert retained.decision is second.decision
