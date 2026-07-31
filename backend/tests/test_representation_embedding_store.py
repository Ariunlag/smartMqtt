"""Isolated tests for stream representation persistence in Qdrant."""

from dataclasses import dataclass

import pytest
from services.database.qdrant import REPRESENTATION_COLLECTION
from services.semantic import RepresentationEmbeddings, StreamRepresentations
from services.store.representation_embedding_store import (
    REPRESENTATION_NAMES,
    RepresentationEmbeddingStore,
    StoredRepresentationEmbedding,
)

TOPIC = "factory/line1/sensor7"
REPRESENTATIONS = StreamRepresentations(
    value_only="Warehouse 01 | 22.5",
    key_only="location | temp",
    key_value="location: Warehouse 01 | temp: 22.5",
    schema="location: string | temp: numeric",
    numeric_key_only="location: Warehouse 01 | temp",
    topic_key_value=("factory line1 sensor7 | location: Warehouse 01 | temp: 22.5"),
)
EMBEDDINGS = RepresentationEmbeddings(
    value_only=(0.0, 0.5),
    key_only=(1.0, 1.5),
    key_value=(2.0, 2.5),
    schema=(3.0, 3.5),
    numeric_key_only=(4.0, 4.5),
    topic_key_value=(5.0, 5.5),
)


@dataclass
class FakePoint:
    vector: list[float]
    payload: dict


class FakeQdrantClient:
    def __init__(self):
        self.upserts = []
        self.points = {}

    def upsert(self, collection, identity, vector, payload):
        self.upserts.append(
            {
                "collection": collection,
                "identity": identity,
                "vector": vector,
                "payload": payload,
            }
        )
        self.points[(collection, identity)] = FakePoint(
            vector=list(vector),
            payload=dict(payload),
        )

    def retrieve(self, collection, identity):
        return self.points.get((collection, identity))


def test_store_writes_six_correctly_mapped_points():
    client = FakeQdrantClient()

    RepresentationEmbeddingStore(client).store(
        TOPIC,
        REPRESENTATIONS,
        EMBEDDINGS,
    )

    assert len(client.upserts) == 6
    assert [item["collection"] for item in client.upserts] == [
        REPRESENTATION_COLLECTION
    ] * 6
    assert [item["identity"] for item in client.upserts] == [
        f"{TOPIC}\0{name}" for name in REPRESENTATION_NAMES
    ]

    representation_values = REPRESENTATIONS.as_dict()
    embedding_values = EMBEDDINGS.as_dict()
    for name, item in zip(REPRESENTATION_NAMES, client.upserts, strict=True):
        assert item["vector"] == list(embedding_values[name])
        assert item["payload"] == {
            "topic": TOPIC,
            "representation_name": name,
            "representation_text": representation_values[name],
        }
        assert "vector" not in item["payload"]


def test_repeated_store_uses_identical_identities():
    client = FakeQdrantClient()
    store = RepresentationEmbeddingStore(client)

    store.store(TOPIC, REPRESENTATIONS, EMBEDDINGS)
    first_identities = [item["identity"] for item in client.upserts]
    store.store(TOPIC, REPRESENTATIONS, EMBEDDINGS)
    second_identities = [item["identity"] for item in client.upserts[6:]]

    assert second_identities == first_identities
    assert len(client.points) == 6


def test_get_returns_structured_stored_representation():
    client = FakeQdrantClient()
    store = RepresentationEmbeddingStore(client)
    store.store(TOPIC, REPRESENTATIONS, EMBEDDINGS)

    result = store.get(TOPIC, "key_value")

    assert result == StoredRepresentationEmbedding(
        topic=TOPIC,
        representation_name="key_value",
        representation_text=REPRESENTATIONS.key_value,
        vector=EMBEDDINGS.key_value,
    )


def test_get_rejects_unknown_representation_name():
    store = RepresentationEmbeddingStore(FakeQdrantClient())

    with pytest.raises(
        ValueError,
        match="Unknown representation name: unsupported",
    ):
        store.get(TOPIC, "unsupported")


def test_get_all_returns_existing_points_in_deterministic_order():
    client = FakeQdrantClient()
    store = RepresentationEmbeddingStore(client)
    store.store(TOPIC, REPRESENTATIONS, EMBEDDINGS)

    results = store.get_all_for_topic(TOPIC)

    assert [result.representation_name for result in results] == list(
        REPRESENTATION_NAMES
    )


def test_missing_points_are_handled_safely():
    client = FakeQdrantClient()
    store = RepresentationEmbeddingStore(client)

    assert store.get(TOPIC, "schema") is None
    assert store.get_all_for_topic(TOPIC) == ()

    store.store(TOPIC, REPRESENTATIONS, EMBEDDINGS)
    del client.points[(REPRESENTATION_COLLECTION, f"{TOPIC}\0numeric_key_only")]

    results = store.get_all_for_topic(TOPIC)
    assert [result.representation_name for result in results] == [
        name for name in REPRESENTATION_NAMES if name != "numeric_key_only"
    ]
