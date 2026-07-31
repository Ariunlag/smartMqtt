"""Qdrant persistence for deterministic stream representation embeddings."""

from __future__ import annotations

from dataclasses import dataclass, fields

from services.database.qdrant import REPRESENTATION_COLLECTION, qdrant_client
from services.semantic.representation_embedder import RepresentationEmbeddings
from services.semantic.representations import StreamRepresentations

REPRESENTATION_NAMES = tuple(field.name for field in fields(StreamRepresentations))


@dataclass(frozen=True, slots=True)
class StoredRepresentationEmbedding:
    """One stored stream representation and its embedding vector."""

    topic: str
    representation_name: str
    representation_text: str
    vector: tuple[float, ...]


class RepresentationEmbeddingStore:
    """Persist and retrieve stream representation embeddings in Qdrant."""

    def __init__(self, client=qdrant_client):
        self.client = client

    def store(
        self,
        topic: str,
        representations: StreamRepresentations,
        embeddings: RepresentationEmbeddings,
    ) -> None:
        """Upsert all six representation vectors for one topic."""
        representation_values = representations.as_dict()
        embedding_values = embeddings.as_dict()

        for name in REPRESENTATION_NAMES:
            self.client.upsert(
                REPRESENTATION_COLLECTION,
                self._identity(topic, name),
                list(embedding_values[name]),
                {
                    "topic": topic,
                    "representation_name": name,
                    "representation_text": representation_values[name],
                },
            )

    def get(
        self,
        topic: str,
        representation_name: str,
    ) -> StoredRepresentationEmbedding | None:
        """Retrieve one representation by its deterministic identity."""
        self._validate_name(representation_name)
        point = self.client.retrieve(
            REPRESENTATION_COLLECTION,
            self._identity(topic, representation_name),
        )
        if point is None:
            return None

        return StoredRepresentationEmbedding(
            topic=point.payload["topic"],
            representation_name=point.payload["representation_name"],
            representation_text=point.payload["representation_text"],
            vector=tuple(point.vector),
        )

    def get_all_for_topic(
        self,
        topic: str,
    ) -> tuple[StoredRepresentationEmbedding, ...]:
        """Return existing points in deterministic representation order."""
        stored = []
        for name in REPRESENTATION_NAMES:
            item = self.get(topic, name)
            if item is not None:
                stored.append(item)
        return tuple(stored)

    @staticmethod
    def _identity(topic: str, representation_name: str) -> str:
        return f"{topic}\0{representation_name}"

    @staticmethod
    def _validate_name(representation_name: str) -> None:
        if representation_name not in REPRESENTATION_NAMES:
            raise ValueError(f"Unknown representation name: {representation_name}")


representation_embedding_store = RepresentationEmbeddingStore()
