from services.database.vector import TOPIC_COLLECTION, vector_store
from services.store.canonical_identity_store import canonical_identity_store


class TopicEmbeddingStore:
    """Persist the authoritative stream-context vector for each canonical topic."""

    def __init__(self, identity_store=canonical_identity_store) -> None:
        self.identity_store = identity_store

    def add(self, item: dict) -> dict:
        vector_store.upsert(
            TOPIC_COLLECTION,
            item["topic"],
            item["embedding"],
            {"topic": item["topic"], "tags": item["tags"]},
        )
        return item

    def get_all(self) -> list[dict]:
        return [
            {
                "topic": point.payload["topic"],
                "embedding": point.vector,
                "tags": point.payload.get("tags", {}),
            }
            for point in vector_store.all_points(TOPIC_COLLECTION)
        ]

    def get(self, topic: str) -> dict | None:
        point = vector_store.retrieve(TOPIC_COLLECTION, topic)
        if point is None:
            return None
        return {
            "topic": point.payload["topic"],
            "embedding": point.vector,
            "tags": point.payload.get("tags", {}),
        }

    def candidates_for(
        self,
        topic: str,
        embedding: list[float],
        limit: int = 10,
    ) -> list[dict]:
        # Bounded over-fetch prevents a dense prefix of inactive aliases from
        # starving the requested active result set. PostgreSQL remains the
        # durable identity authority while pgvector supplies ANN candidates.
        points = vector_store.nearest_many(
            TOPIC_COLLECTION,
            embedding,
            limit=min(max(limit * 8, 64), 256),
        )
        topics = [point.payload["topic"] for point in points]
        identities = self.identity_store.resolve_many(topics + [topic])
        source_root = identities.get(topic, topic)
        return [
            {
                "topic": point.payload["topic"],
                "embedding": point.vector,
                "tags": point.payload.get("tags", {}),
            }
            for point in points
            if point.payload["topic"] != topic
            and identities.get(point.payload["topic"], point.payload["topic"])
            == point.payload["topic"]
            and identities.get(point.payload["topic"], point.payload["topic"])
            != source_root
        ][:limit]


topic_embedding_store = TopicEmbeddingStore()
