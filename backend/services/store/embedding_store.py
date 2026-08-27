import numpy as np
from services.database.postgres import postgres_client
from services.database.vector import GROUP_COLLECTION, TOPIC_COLLECTION, vector_store
from services.store.canonical_identity_store import canonical_identity_store

# Serializes concurrent group assignment so the nearest-centroid read and the
# subsequent group create/centroid update cannot race (safe across workers).
GROUP_ASSIGNMENT_LOCK = 91847362
TAG_GROUP_CONTRACT_VERSION = "shared-tag-value-v1"


class TopicEmbeddingStore:
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


class TagSetStore:
    """Persist exploratory tag-value centroid groups over shared pair evidence."""

    @staticmethod
    def _numeric_id(set_id: str) -> int:
        if not set_id.startswith("set_"):
            raise ValueError(f"Invalid tag group id: {set_id}")
        return int(set_id.removeprefix("set_"))

    @staticmethod
    def _contract_payload() -> dict[str, str]:
        return {"contract": TAG_GROUP_CONTRACT_VERSION}

    def find_or_create_set(
        self,
        tag_key: str,
        tag_value: str,
        vector: list[float],
        threshold: float,
        topic: str,
    ) -> str:
        with postgres_client.transaction() as conn:
            # Old centroid representations are intentionally invisible here. Mixing
            # a prior key+value centroid with the current value-only evidence would
            # make cosine comparisons meaningless on existing volumes.
            conn.execute("SELECT pg_advisory_xact_lock(%s)", (GROUP_ASSIGNMENT_LOCK,))
            nearest = vector_store.nearest(
                GROUP_COLLECTION,
                vector,
                payload_filter=self._contract_payload(),
                conn=conn,
            )
            if nearest and nearest.score >= threshold:
                set_id = nearest.payload["set_id"]
                group_id = self._numeric_id(set_id)
                old_vector = np.asarray(nearest.vector, dtype=float)
                count_row = conn.execute(
                    """
                    SELECT count(*) AS count FROM tag_group_values
                    WHERE group_id = %s
                    """,
                    (group_id,),
                ).fetchone()
                old_count = int(count_row["count"])
            else:
                row = conn.execute(
                    "INSERT INTO tag_groups DEFAULT VALUES RETURNING id"
                ).fetchone()
                group_id = row["id"]
                set_id = f"set_{group_id}"
                old_vector = np.asarray(vector, dtype=float)
                old_count = 0

            inserted = conn.execute(
                """
                INSERT INTO tag_group_values(group_id, tag_key, tag_value)
                VALUES (%s, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                (group_id, tag_key, tag_value),
            ).rowcount
            conn.execute(
                """
                INSERT INTO tag_group_topics(group_id, topic)
                VALUES (%s, %s)
                ON CONFLICT DO NOTHING
                """,
                (group_id, topic),
            )

            if inserted:
                centroid = (
                    (old_vector * old_count + np.asarray(vector, dtype=float))
                    / (old_count + 1)
                ).tolist()
            else:
                centroid = old_vector.tolist()

            vector_store.upsert(
                GROUP_COLLECTION,
                set_id,
                centroid,
                {
                    "set_id": set_id,
                    "contract": TAG_GROUP_CONTRACT_VERSION,
                    "evidence_id": "value",
                    "source": "tag",
                },
                conn=conn,
            )
        return set_id

    def _active_set_ids(self) -> set[str]:
        return {
            point.payload["set_id"]
            for point in vector_store.all_points(GROUP_COLLECTION)
            if point.payload.get("contract") == TAG_GROUP_CONTRACT_VERSION
            and point.payload.get("set_id")
        }

    def get_all(self) -> list[dict]:
        active_set_ids = self._active_set_ids()
        if not active_set_ids:
            return []
        rows = postgres_client.fetch_all(
            """
            SELECT g.id,
                   array_agg(DISTINCT gv.tag_value ORDER BY gv.tag_value) AS tags,
                   count(DISTINCT COALESCE(identity.canonical_topic, gt.topic))
                       AS topic_count
            FROM tag_groups g
            JOIN tag_group_values gv ON gv.group_id = g.id
            LEFT JOIN tag_group_topics gt ON gt.group_id = g.id
            LEFT JOIN duplicate_canonical_topics identity ON identity.topic = gt.topic
            GROUP BY g.id
            ORDER BY g.id
            """
        )
        return [
            {
                "id": f"set_{row['id']}",
                "tags": row["tags"],
                "topic_count": row["topic_count"],
            }
            for row in rows
            if f"set_{row['id']}" in active_set_ids
        ]

    def get_topics(self, set_id: str) -> list[str]:
        if set_id not in self._active_set_ids():
            return []
        rows = postgres_client.fetch_all(
            """
            SELECT DISTINCT COALESCE(identity.canonical_topic, membership.topic) AS topic
            FROM tag_group_topics membership
            LEFT JOIN duplicate_canonical_topics identity
                ON identity.topic = membership.topic
            WHERE membership.group_id = %s
            ORDER BY topic
            """,
            (self._numeric_id(set_id),),
        )
        return [row["topic"] for row in rows]


topic_embedding_store = TopicEmbeddingStore()
tagset_store = TagSetStore()
