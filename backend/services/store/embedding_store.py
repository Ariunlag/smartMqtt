import numpy as np

from services.database.postgres import postgres_client
from services.database.qdrant import (
    GROUP_COLLECTION,
    TAG_COLLECTION,
    TOPIC_COLLECTION,
    qdrant_client,
)


class TopicEmbeddingStore:
    def add(self, item: dict) -> dict:
        qdrant_client.upsert(
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
            for point in qdrant_client.all_points(TOPIC_COLLECTION)
        ]

    def candidates_for(
        self,
        topic: str,
        embedding: list[float],
        limit: int = 10,
    ) -> list[dict]:
        return [
            {
                "topic": point.payload["topic"],
                "embedding": point.vector,
                "tags": point.payload.get("tags", {}),
            }
            for point in qdrant_client.nearest_many(
                TOPIC_COLLECTION,
                embedding,
                limit=limit + 1,
            )
            if point.payload["topic"] != topic
        ][:limit]


class TagSetStore:
    @staticmethod
    def _numeric_id(set_id: str) -> int:
        if not set_id.startswith("set_"):
            raise ValueError(f"Invalid tag group id: {set_id}")
        return int(set_id.removeprefix("set_"))

    def store_tag_embedding(
        self,
        topic: str,
        tag_key: str,
        tag_value: str,
        vector: list[float],
    ):
        identity = f"{topic}\0{tag_key}\0{tag_value}"
        qdrant_client.upsert(
            TAG_COLLECTION,
            identity,
            vector,
            {
                "topic": topic,
                "key": tag_key,
                "value": tag_value,
                "representation": f"{tag_key} {tag_value}",
            },
        )

    def find_or_create_set(
        self,
        tag_key: str,
        tag_value: str,
        vector: list[float],
        threshold: float,
        topic: str,
    ) -> str:
        nearest = qdrant_client.nearest(GROUP_COLLECTION, vector)
        if nearest and nearest.score >= threshold:
            set_id = nearest.payload["set_id"]
            group_id = self._numeric_id(set_id)
            old_vector = np.asarray(nearest.vector, dtype=float)
            count_row = postgres_client.fetch_one(
                """
                SELECT count(*) AS count FROM tag_group_values
                WHERE group_id = %s
                """,
                (group_id,),
            )
            old_count = int(count_row["count"])
        else:
            row = postgres_client.fetch_one(
                "INSERT INTO tag_groups DEFAULT VALUES RETURNING id"
            )
            group_id = row["id"]
            set_id = f"set_{group_id}"
            old_vector = np.asarray(vector, dtype=float)
            old_count = 0

        inserted = postgres_client.execute(
            """
            INSERT INTO tag_group_values(group_id, tag_key, tag_value)
            VALUES (%s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (group_id, tag_key, tag_value),
        )
        postgres_client.execute(
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

        qdrant_client.upsert(
            GROUP_COLLECTION,
            set_id,
            centroid,
            {"set_id": set_id},
        )
        return set_id

    def get_all(self) -> list[dict]:
        rows = postgres_client.fetch_all(
            """
            SELECT g.id,
                   array_agg(DISTINCT gv.tag_value ORDER BY gv.tag_value) AS tags,
                   count(DISTINCT gt.topic) AS topic_count
            FROM tag_groups g
            JOIN tag_group_values gv ON gv.group_id = g.id
            LEFT JOIN tag_group_topics gt ON gt.group_id = g.id
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
        ]

    def get_topics(self, set_id: str) -> list[str]:
        rows = postgres_client.fetch_all(
            """
            SELECT topic FROM tag_group_topics
            WHERE group_id = %s ORDER BY topic
            """,
            (self._numeric_id(set_id),),
        )
        return [row["topic"] for row in rows]


topic_embedding_store = TopicEmbeddingStore()
tagset_store = TagSetStore()
