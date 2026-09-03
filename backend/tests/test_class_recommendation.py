import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from models.mqtt_message import MQTTMessage
from services.class_recommendation.application import ClassRecommendationApplication
from services.class_recommendation.domain import (
    REPRESENTATION_CONTRACT_VERSION,
    ClassPairPrototype,
    ClassProfile,
    PairEmbeddingRecord,
    PairIdentity,
    PairRepresentation,
)
from services.class_recommendation.embedding import PairEmbedder, PairEmbeddingError
from services.class_recommendation.evidence import PAIR_EVIDENCE_IDS
from services.class_recommendation.matching import PairClassMatcher
from services.class_recommendation.profiling import StreamProfiler
from services.class_recommendation.representations import PairRepresentationBuilder
from services.class_recommendation.stores import PairEmbeddingStore


class CountingModel:
    def __init__(self):
        self.calls = []

    def encode(self, texts):
        self.calls.append(tuple(texts))
        return [
            (float(index + 1), float(len(text) + 1)) for index, text in enumerate(texts)
        ]


def test_each_pair_keeps_identity_and_exact_registered_views():
    profile = StreamProfiler().profile(
        "building/room",
        {"location": "Room_2"},
        {"temperature": 22.5, "status": "active"},
    )
    pairs = PairRepresentationBuilder.build(
        profile,
        canonical_topic="building/room",
        original_topic="building/room",
        representation_version=7,
    )

    assert [pair.identity.value for pair in pairs] == [
        "tag:location:string",
        "field:status:string",
        "field:temperature:numeric",
    ]
    assert tuple(name for name, _ in pairs[0].texts) == PAIR_EVIDENCE_IDS
    assert tuple(name for name, _ in pairs[2].texts) == PAIR_EVIDENCE_IDS
    assert pairs[2].text_for("key_value") == "temperature: 22.5"
    assert pairs[2].text_for("numeric_key") is None
    assert all(" | " not in text for pair in pairs for _, text in pair.texts)


def test_pair_embedder_batches_once_without_collapsing_pair_or_view_identity():
    model = CountingModel()
    profile = StreamProfiler().profile("topic", {"room": "A"}, {"value": 1.0})
    pairs = PairRepresentationBuilder.build(
        profile,
        canonical_topic="topic",
        original_topic="topic",
        representation_version=1,
    )

    embedded = PairEmbedder(model).embed(pairs)

    assert len(model.calls) == 1
    assert len(model.calls[0]) == 8
    assert len(embedded) == 2
    assert len(embedded[0].vectors) == 4
    assert len(embedded[1].vectors) == 4


def test_vector_pair_store_round_trip_preserves_views_and_text():
    class FakeVectorStore:
        def __init__(self):
            self.points = []

        def upsert(self, collection, identity, vector, payload):
            self.points.append(SimpleNamespace(vector=vector, payload=payload))

        def all_points(self, collection):
            return list(self.points)

        def points_where(self, collection, filters):
            return [
                point
                for point in self.points
                if all(point.payload.get(key) == value for key, value in filters.items())
            ]

        def delete_where(self, collection, filters):
            self.points = [
                point
                for point in self.points
                if point.payload.get("canonical_topic") != filters["canonical_topic"]
            ]

    model = CountingModel()
    profile = StreamProfiler().profile("topic", {}, {"temperature": 22.5})
    representations = PairRepresentationBuilder.build(
        profile,
        canonical_topic="topic",
        original_topic="topic",
        representation_version=3,
    )
    embedded = PairEmbedder(model).embed(representations)
    store = PairEmbeddingStore(FakeVectorStore())

    store.replace_topic("topic", embedded)
    restored = store.get_topic("topic")

    assert len(restored) == 1
    assert restored[0].representation.texts == representations[0].texts
    assert restored[0].vectors == embedded[0].vectors
    assert restored[0].representation.representation_version == 3


def test_embedding_failure_is_explicit_and_never_uses_lexical_fallback():
    class BrokenModel:
        def encode(self, texts):
            raise OSError("offline")

    profile = StreamProfiler().profile("topic", {}, {"temperature": 1.0})
    pairs = PairRepresentationBuilder.build(
        profile,
        canonical_topic="topic",
        original_topic="topic",
        representation_version=1,
    )
    with pytest.raises(PairEmbeddingError, match="model failed"):
        PairEmbedder(BrokenModel()).embed(pairs)


def _pair(key, vectors, *, datatype="numeric"):
    identity = PairIdentity("field", key, datatype)
    representation = PairRepresentation(
        canonical_topic="candidate",
        original_topic="candidate",
        identity=identity,
        raw_key=key,
        raw_value="1",
        normalized_key=key,
        normalized_value="1",
        datatype=datatype,
        representation_version=1,
        texts=(),
    )
    return PairEmbeddingRecord(representation, tuple(vectors.items()))


def _prototype(class_id, key, vectors, *, datatype="numeric", version=1):
    return ClassPairPrototype(
        class_id=class_id,
        class_name=class_id,
        identity=PairIdentity("field", key, datatype),
        centroids=tuple(vectors.items()),
        member_count=2,
        prototype_version=version,
    )


def test_matching_is_one_to_one_deterministic_and_keeps_coverage_and_unmatched_pairs():
    four = {
        "key": (1.0, 0.0),
        "value": (1.0, 0.0),
        "key_value": (1.0, 0.0),
        "schema": (1.0, 0.0),
    }
    pairs = (_pair("temp", four), _pair("temperature", four))
    prototype = _prototype("temperature", "temperature", four)
    profile = ClassProfile("temperature", "Temperature", 3, (prototype,), None)

    first = PairClassMatcher.recommend(
        canonical_topic="candidate",
        original_topic="candidate",
        topic_version=2,
        pairs=pairs,
        stream_context=None,
        profile=profile,
        duplicate_pending=True,
    )
    second = PairClassMatcher.recommend(
        canonical_topic="candidate",
        original_topic="candidate",
        topic_version=2,
        pairs=tuple(reversed(pairs)),
        stream_context=None,
        profile=profile,
        duplicate_pending=True,
    )

    assert first == second
    assert first.coverage.matched_pair_count == 1
    assert first.coverage.candidate_coverage == 0.5
    assert first.coverage.prototype_coverage == 1.0
    assert first.matched_pairs[0].candidate.normalized_key == "temp"
    assert first.unmatched_candidate_pairs[0].normalized_key == "temperature"
    assert first.duplicate_pending is True
    assert first.valid_channels == PAIR_EVIDENCE_IDS
    assert "numeric_key" not in first.valid_channels


def test_stream_context_is_separate_registry_evidence_without_numeric_special_case():
    four = {
        "key": (1.0, 0.0),
        "value": (1.0, 0.0),
        "key_value": (1.0, 0.0),
        "schema": (1.0, 0.0),
    }
    profile = ClassProfile(
        "status",
        "Status",
        1,
        (_prototype("status", "status", four, datatype="string"),),
        (1.0, 0.0),
    )
    result = PairClassMatcher.recommend(
        canonical_topic="candidate",
        original_topic="candidate",
        topic_version=1,
        pairs=(_pair("status", four, datatype="string"),),
        stream_context=(1.0, 0.0),
        profile=profile,
        duplicate_pending=False,
    )
    assert result.channel_scores.get("stream_context") == pytest.approx(1.0)
    assert result.channel_scores.get("numeric_key") is None
    assert result.overall_score == pytest.approx(1.0)


class FakeClassStore:
    def get_all(self):
        return []

    def classes_for_topic(self, topic):
        return []


class FakeIdentityStore:
    def resolve_canonical(self, topic):
        return topic

    def is_duplicate_alias(self, topic):
        return False


class FakeTopicEmbeddingStore:
    def __init__(self):
        self.rows = {
            "sensor": {"topic": "sensor", "embedding": [1.0, 0.0], "tags": {}},
            "reference": {
                "topic": "reference",
                "embedding": [1.0, 0.0],
                "tags": {},
            },
        }

    def get(self, topic):
        return self.rows.get(topic)


class FakeDupeStore:
    def has_pending(self, topic):
        return False


class FakePairStore:
    def __init__(self):
        self.rows = {}

    def replace_topic(self, topic, records):
        self.rows[topic] = records

    def get_topic(self, topic):
        return self.rows.get(topic, ())

    def remove_topic(self, topic):
        self.rows.pop(topic, None)


class FakePrototypeStore:
    def replace_class(self, *args):
        pass

    def remove_class(self, class_id):
        pass


class FakeMetadataStore:
    def __init__(self):
        self.rows = {}

    def topic_state(self, topic):
        return self.rows.get(topic)

    def set_topic_state(self, topic, version, fingerprint):
        self.rows[topic] = {
            "canonical_topic": topic,
            "representation_version": version,
            "representation_fingerprint": fingerprint,
            "representation_contract_version": REPRESENTATION_CONTRACT_VERSION,
        }


class ActionClassStore:
    def __init__(self):
        self.record = {
            "class_id": "temperature-id",
            "name": "Temperature",
            "topics": ["reference"],
            "profile_version": 1,
        }

    def get_all(self):
        return [dict(self.record)]

    def get(self, name):
        return dict(self.record) if name == self.record["name"] else None

    def get_by_id(self, class_id):
        return dict(self.record) if class_id == self.record["class_id"] else None

    def classes_for_topic(self, topic):
        return [dict(self.record)] if topic in self.record["topics"] else []

    def update(self, name, topics):
        self.record["topics"] = list(dict.fromkeys(topics))
        self.record["profile_version"] += 1
        return dict(self.record)


class ActionMetadataStore(FakeMetadataStore):
    def __init__(self):
        super().__init__()
        for topic in ("sensor", "reference"):
            self.rows[topic] = {
                "canonical_topic": topic,
                "representation_version": 1,
                "representation_fingerprint": "fixture",
                "representation_contract_version": REPRESENTATION_CONTRACT_VERSION,
            }
        self.rejections = set()
        self.dismissals = set()
        self.audits = []

    def all_topic_states(self):
        return list(self.rows.values())

    def is_suppressed(self, topic, class_id, topic_version, class_version):
        identity = (topic, class_id, topic_version, class_version)
        return identity in self.rejections or identity in self.dismissals

    def reject(self, topic, class_id, topic_version, class_version):
        self.rejections.add((topic, class_id, topic_version, class_version))

    def dismiss(self, topic, class_id, topic_version, class_version):
        self.dismissals.add((topic, class_id, topic_version, class_version))

    def clear_suppression(self, topic, class_id):
        self.rejections = {
            item for item in self.rejections if item[:2] != (topic, class_id)
        }
        self.dismissals = {
            item for item in self.dismissals if item[:2] != (topic, class_id)
        }

    def audit(self, *, action_type, details):
        self.audits.append((action_type, dict(details)))
        return f"event-{len(self.audits)}"


def _action_application():
    model = CountingModel()
    class_store = ActionClassStore()
    pair_store = FakePairStore()
    profile = StreamProfiler().profile("sensor", {}, {"temperature": 1.0})
    pairs = PairRepresentationBuilder.build(
        profile,
        canonical_topic="sensor",
        original_topic="sensor",
        representation_version=1,
    )
    pair_store.replace_topic("sensor", PairEmbedder(model).embed(pairs))
    reference_pairs = PairRepresentationBuilder.build(
        profile,
        canonical_topic="reference",
        original_topic="reference",
        representation_version=1,
    )
    pair_store.replace_topic("reference", PairEmbedder(model).embed(reference_pairs))
    metadata = ActionMetadataStore()
    application = ClassRecommendationApplication(
        model=model,
        class_store=class_store,
        identity_store=FakeIdentityStore(),
        topic_embedding_store=FakeTopicEmbeddingStore(),
        dupe_store=FakeDupeStore(),
        pair_store=pair_store,
        prototype_store=FakePrototypeStore(),
        metadata_store=metadata,
    )
    application.warm_profiles()
    return application, class_store, metadata


def _message(value=1.0, status="active"):
    return MQTTMessage(
        topic="sensor",
        tags={"status": status},
        fields={"temperature": value},
        timestamp=datetime.now(UTC),
    )


def _application(model):
    return ClassRecommendationApplication(
        model=model,
        class_store=FakeClassStore(),
        identity_store=FakeIdentityStore(),
        topic_embedding_store=FakeTopicEmbeddingStore(),
        dupe_store=FakeDupeStore(),
        pair_store=FakePairStore(),
        prototype_store=FakePrototypeStore(),
        metadata_store=FakeMetadataStore(),
    )


@pytest.mark.asyncio
async def test_numeric_variation_does_not_reembed_or_increment_representation_version():
    model = CountingModel()
    application = _application(model)
    assert await application.observe(_message(1.0)) is True
    assert await application.observe(_message(2.0)) is False
    assert len(model.calls) == 1
    assert application.metadata_store.rows["sensor"]["representation_version"] == 1


@pytest.mark.asyncio
async def test_representation_contract_change_forces_rematerialization():
    model = CountingModel()
    application = _application(model)
    assert await application.observe(_message(1.0)) is True
    application.metadata_store.rows["sensor"][
        "representation_contract_version"
    ] = "obsolete-contract"

    assert await application.observe(_message(2.0)) is True
    assert len(model.calls) == 2
    assert application.metadata_store.rows["sensor"]["representation_version"] == 2
    assert (
        application.metadata_store.rows["sensor"]["representation_contract_version"]
        == REPRESENTATION_CONTRACT_VERSION
    )


@pytest.mark.asyncio
async def test_incomplete_persisted_pair_material_is_rebuilt_after_restart():
    model = CountingModel()
    application = _application(model)
    assert await application.observe(_message(1.0)) is True
    stored = application.pair_store.rows["sensor"]
    first = stored[0]
    application.pair_store.rows["sensor"] = (
        PairEmbeddingRecord(first.representation, first.vectors[:-1]),
    ) + stored[1:]
    application._materialized_topics.clear()

    assert await application.observe(_message(1.0)) is True
    assert len(model.calls) == 2
    assert application.metadata_store.rows["sensor"]["representation_version"] == 2


@pytest.mark.asyncio
async def test_categorical_change_refreshes_once_and_concurrent_same_topic_is_coalesced_by_lock():
    model = CountingModel()
    application = _application(model)
    results = await asyncio.gather(
        application.observe(_message(status="active")),
        application.observe(_message(status="active")),
    )
    assert sorted(results) == [False, True]
    assert len(model.calls) == 1

    assert await application.observe(_message(status="inactive")) is False
    assert await application.observe(_message(status="inactive")) is False
    assert await application.observe(_message(status="inactive")) is True
    assert len(model.calls) == 2
    assert application.metadata_store.rows["sensor"]["representation_version"] == 2


def test_accept_uses_current_versions_updates_membership_profile_and_audit_provenance():
    application, class_store, metadata = _action_application()
    recommendation = application.recommendations_for_topic("sensor").recommendations[0]

    result = application.apply_action(
        action="RECOMMENDATION_ACCEPT",
        class_name="Temperature",
        topic="sensor",
        topic_version=recommendation.topic_representation_version,
        class_profile_version=recommendation.class_profile_version,
        recommendation_id=recommendation.recommendation_id,
    )

    assert class_store.record["topics"] == ["reference", "sensor"]
    assert result["class_profile_version"] == 2
    assert metadata.audits[0][0] == "RECOMMENDATION_ACCEPT"
    assert (
        metadata.audits[0][1]["recommendation"].recommendation_id
        == recommendation.recommendation_id
    )
    assert application._profiles["temperature-id"].pair_prototypes[0].member_count == 2
    assert application.recommendations_for_topic("sensor").recommendations == ()


@pytest.mark.parametrize(
    ("action", "store_name"),
    (
        ("RECOMMENDATION_REJECT", "rejections"),
        ("RECOMMENDATION_DISMISS", "dismissals"),
    ),
)
def test_reject_and_dismiss_suppress_only_the_unchanged_recommendation(
    action, store_name
):
    application, class_store, metadata = _action_application()
    recommendation = application.recommendations_for_topic("sensor").recommendations[0]
    application.apply_action(
        action=action,
        class_name="Temperature",
        topic="sensor",
        topic_version=1,
        class_profile_version=1,
        recommendation_id=recommendation.recommendation_id,
    )
    assert class_store.record["topics"] == ["reference"]
    assert len(getattr(metadata, store_name)) == 1
    assert application.recommendations_for_topic("sensor").recommendations == ()


def test_stale_recommendation_action_is_rejected_without_mutation():
    from services.class_recommendation.application import StaleRecommendationError

    application, class_store, metadata = _action_application()
    recommendation = application.recommendations_for_topic("sensor").recommendations[0]
    with pytest.raises(StaleRecommendationError, match="stale"):
        application.apply_action(
            action="RECOMMENDATION_ACCEPT",
            class_name="Temperature",
            topic="sensor",
            topic_version=1,
            class_profile_version=99,
            recommendation_id=recommendation.recommendation_id,
        )
    assert class_store.record["topics"] == ["reference"]
    assert metadata.audits == []
