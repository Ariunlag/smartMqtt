from services.class_recommendation.discovery import RecommendedClassDiscovery
from services.class_recommendation.domain import REPRESENTATION_CONTRACT_VERSION


class BulkMetadataStore:
    def __init__(self):
        self.calls = 0

    def all_topic_states(self):
        self.calls += 1
        return [
            {
                "canonical_topic": "topic/a",
                "representation_version": 1,
                "representation_fingerprint": "a",
                "representation_contract_version": REPRESENTATION_CONTRACT_VERSION,
            },
            {
                "canonical_topic": "topic/b",
                "representation_version": 2,
                "representation_fingerprint": "b",
                "representation_contract_version": REPRESENTATION_CONTRACT_VERSION,
            },
        ]

    def topic_state(self, topic):
        raise AssertionError("bulk discovery must not re-read topic_state per topic")


class BulkIdentityStore:
    def __init__(self):
        self.calls = []

    def resolve_many(self, topics):
        self.calls.append(tuple(topics))
        return {topic: topic for topic in topics}

    def is_duplicate_alias(self, topic):
        raise AssertionError("bulk discovery must not query alias status per topic")


class BulkPairStore:
    def __init__(self):
        self.calls = []

    def get_topics(self, topics):
        self.calls.append(tuple(topics))
        return {topic: () for topic in topics}

    def get_topic(self, topic):
        raise AssertionError("bulk discovery must not load pairs per topic")


class BulkStreamStore:
    def __init__(self):
        self.calls = []

    def get_many(self, topics):
        self.calls.append(tuple(topics))
        return {
            "topic/a": {"embedding": [1.0, 0.0]},
            "topic/b": {"embedding": [0.0, 1.0]},
        }

    def get(self, topic):
        raise AssertionError("bulk discovery must not load stream vectors per topic")


class BulkDupeStore:
    def __init__(self):
        self.calls = []

    def pending_topics(self, topics):
        self.calls.append(tuple(topics))
        return {"topic/b"}

    def has_pending(self, topic):
        raise AssertionError("pairwise discovery must not query duplicate state")


def test_active_material_prefetches_each_database_dimension_once():
    metadata = BulkMetadataStore()
    identity = BulkIdentityStore()
    pairs = BulkPairStore()
    streams = BulkStreamStore()
    dupes = BulkDupeStore()
    discovery = RecommendedClassDiscovery(
        metadata_store=metadata,
        pair_store=pairs,
        topic_embedding_store=streams,
        identity_store=identity,
        dupe_store=dupes,
    )

    topics, versions, pairs_by_topic, stream_vectors, pending = discovery._active_material()

    assert topics == ("topic/a", "topic/b")
    assert versions == {"topic/a": 1, "topic/b": 2}
    assert pairs_by_topic == {"topic/a": (), "topic/b": ()}
    assert stream_vectors == {
        "topic/a": (1.0, 0.0),
        "topic/b": (0.0, 1.0),
    }
    assert pending == {"topic/b"}
    assert metadata.calls == 1
    assert identity.calls == [("topic/a", "topic/b")]
    assert pairs.calls == [("topic/a", "topic/b")]
    assert streams.calls == [("topic/a", "topic/b")]
    assert dupes.calls == [("topic/a", "topic/b")]
