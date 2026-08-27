import pytest

from services.class_recommendation.discovery import (
    RecommendedClassDiscovery,
    RecommendedClassDiscoveryConfig,
)
from services.class_recommendation.domain import (
    REPRESENTATION_CONTRACT_VERSION,
    PairEmbeddingRecord,
    PairIdentity,
    PairRepresentation,
)
from services.class_recommendation.evidence import PAIR_EVIDENCE_IDS


def _record(topic, source, key, datatype, vector):
    identity = PairIdentity(source, key, datatype)
    views = PAIR_EVIDENCE_IDS
    representation = PairRepresentation(
        canonical_topic=topic,
        original_topic=topic,
        identity=identity,
        raw_key=key,
        raw_value="fixture",
        normalized_key=key,
        normalized_value="fixture",
        datatype=datatype,
        representation_version=1,
        texts=tuple((name, f"{key}:{name}") for name in views),
    )
    return PairEmbeddingRecord(
        representation,
        tuple((name, tuple(vector)) for name in views),
    )


class FakeMetadataStore:
    def __init__(self, topics):
        self.rows = {
            topic: {
                "canonical_topic": topic,
                "representation_version": 1,
                "representation_fingerprint": f"fp-{topic}",
                "representation_contract_version": REPRESENTATION_CONTRACT_VERSION,
            }
            for topic in topics
        }

    def all_topic_states(self):
        return [dict(row) for row in self.rows.values()]

    def topic_state(self, topic):
        row = self.rows.get(topic)
        return dict(row) if row else None


class FakePairStore:
    def __init__(self):
        same = (1.0, 0.0)
        different = (0.0, 1.0)
        self.rows = {
            "a": (
                _record("a", "tag", "unit", "string", same),
                _record("a", "field", "temperature", "numeric", same),
            ),
            "b": (
                _record("b", "tag", "unit", "string", same),
                _record("b", "field", "temp", "numeric", same),
            ),
            "c": (
                _record("c", "tag", "zone", "string", different),
                _record("c", "field", "pressure", "numeric", different),
            ),
        }

    def get_topic(self, topic):
        return self.rows.get(topic, ())


class FakeTopicEmbeddingStore:
    def __init__(self):
        self.rows = {
            "a": {"embedding": [1.0, 0.0]},
            "b": {"embedding": [1.0, 0.0]},
            "c": {"embedding": [0.0, 1.0]},
        }

    def get(self, topic):
        return self.rows.get(topic)


class FakeIdentityStore:
    def __init__(self, aliases=()):
        self.aliases = set(aliases)

    def is_duplicate_alias(self, topic):
        return topic in self.aliases


class FakeDupeStore:
    def __init__(self, pending=()):
        self.pending = set(pending)

    def has_pending(self, topic):
        return topic in self.pending


def _labels(channel, matrix):
    assert len(matrix) == 3
    if channel in {"key", "schema", "stream_context"}:
        return (0, 0, -1)
    return (-1, -1, -1)


def _discovery(*, aliases=(), pending=(), labels=_labels):
    return RecommendedClassDiscovery(
        metadata_store=FakeMetadataStore(("a", "b", "c")),
        pair_store=FakePairStore(),
        topic_embedding_store=FakeTopicEmbeddingStore(),
        identity_store=FakeIdentityStore(aliases),
        dupe_store=FakeDupeStore(pending),
        config=RecommendedClassDiscoveryConfig(min_cluster_size=2),
        cluster_labels=labels,
    )


def test_system_candidates_merge_independent_channel_reasons_and_keep_pair_evidence():
    result = _discovery(pending=("b",)).discover()

    assert result.available_topics == ("a", "b", "c")
    assert result.strategy.strategy_id == "independent_hdbscan"
    assert tuple(item.strategy_id for item in result.strategy_catalog) == (
        "independent_hdbscan",
    )
    assert tuple(item.evidence_id for item in result.evidence_catalog) == (
        "key",
        "value",
        "key_value",
        "schema",
        "stream_context",
    )
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.member_topics == ("a", "b")
    assert candidate.anchor_topic == "a"
    assert candidate.discovery_channels == ("key", "schema", "stream_context")
    assert len(candidate.evidence) == 1

    evidence = candidate.evidence[0]
    assert evidence.topic == "b"
    assert evidence.duplicate_pending is True
    assert evidence.coverage.matched_pair_count == 2
    assert evidence.channel_scores.get("stream_context") == 1.0
    assert {match.candidate.source for match in evidence.matched_pairs} == {
        "tag",
        "field",
    }
    assert all(match.scores.get("numeric_key") is None for match in evidence.matched_pairs)
    assert any(
        match.candidate.normalized_key == "temp"
        and match.prototype.normalized_key == "temperature"
        for match in evidence.matched_pairs
    )


def test_confirmed_duplicate_alias_is_not_an_independent_candidate_member():
    def two_topic_labels(channel, matrix):
        assert len(matrix) == 2
        return (0, 0) if channel == "key" else (-1, -1)

    result = _discovery(aliases=("b",), labels=two_topic_labels).discover()

    assert result.available_topics == ("a", "c")
    assert all("b" not in candidate.member_topics for candidate in result.candidates)


def test_unknown_strategy_is_rejected_without_touching_evidence_contract():
    with pytest.raises(ValueError, match="Unknown recommendation strategy"):
        _discovery().discover("not-a-strategy")
