from services.database.postgres import postgres_client
from services.store.canonical_identity_store import canonical_identity_store


class ClassStore:
    def __init__(self, identity_store=canonical_identity_store) -> None:
        self.identity_store = identity_store

    def _canonicalize(self, topics: list[str]) -> list[str]:
        identities = self.identity_store.resolve_many(topics)
        return list(dict.fromkeys(identities.get(topic, topic) for topic in topics))

    def get_all(self) -> list[dict]:
        rows = postgres_client.fetch_all(
            """
            SELECT c.name, COALESCE(
                array_agg(membership.topic ORDER BY membership.position)
                    FILTER (WHERE membership.topic IS NOT NULL),
                ARRAY[]::text[]
            ) AS topics
            FROM classes c
            LEFT JOIN LATERAL (
                SELECT COALESCE(identity.canonical_topic, ct.topic) AS topic,
                       min(ct.position) AS position
                FROM class_topics ct
                LEFT JOIN duplicate_canonical_topics identity
                    ON identity.topic = ct.topic
                WHERE ct.class_name = c.name
                GROUP BY COALESCE(identity.canonical_topic, ct.topic)
            ) membership ON TRUE
            GROUP BY c.name
            ORDER BY c.name
            """
        )
        return [{"name": row["name"], "topics": row["topics"]} for row in rows]

    def add(self, item: dict) -> dict:
        topics = self._canonicalize(item["topics"])
        with postgres_client.transaction() as conn:
            conn.execute("INSERT INTO classes(name) VALUES (%s)", (item["name"],))
            for position, topic in enumerate(topics):
                conn.execute(
                    """
                    INSERT INTO class_topics(class_name, topic, position)
                    VALUES (%s, %s, %s)
                    """,
                    (item["name"], topic, position),
                )
        return {"name": item["name"], "topics": topics}

    def update(self, name: str, topics: list[str]) -> dict | None:
        topics = self._canonicalize(topics)
        with postgres_client.transaction() as conn:
            found = conn.execute(
                "SELECT 1 FROM classes WHERE name = %s",
                (name,),
            ).fetchone()
            if not found:
                return None
            conn.execute("DELETE FROM class_topics WHERE class_name = %s", (name,))
            for position, topic in enumerate(topics):
                conn.execute(
                    """
                    INSERT INTO class_topics(class_name, topic, position)
                    VALUES (%s, %s, %s)
                    """,
                    (name, topic, position),
                )
        return {"name": name, "topics": topics}

    def remove(self, name: str) -> bool:
        return (
            postgres_client.execute(
                "DELETE FROM classes WHERE name = %s",
                (name,),
            )
            > 0
        )


class DupeStore:
    @staticmethod
    def _pair(topic_a: str, topic_b: str) -> tuple[str, str]:
        return tuple(sorted((topic_a, topic_b)))

    def get_all(self) -> list[dict]:
        rows = postgres_client.fetch_all(
            """
            SELECT topic_a, topic_b, score, status
            FROM duplicates
            ORDER BY created_at
            """
        )
        return [
            {
                "topics": [row["topic_a"], row["topic_b"]],
                "score": row["score"],
                "status": row["status"],
            }
            for row in rows
        ]

    def get_pair(self, topic_a: str, topic_b: str) -> dict | None:
        topic_a, topic_b = self._pair(topic_a, topic_b)
        row = postgres_client.fetch_one(
            """
            SELECT topic_a, topic_b, score, status FROM duplicates
            WHERE topic_a = %s AND topic_b = %s
            """,
            (topic_a, topic_b),
        )
        return self._record(row) if row else None

    def create_pending(
        self, topic_a: str, topic_b: str, score: float
    ) -> tuple[dict, bool]:
        """Create one logical pending event and preserve terminal decisions."""
        topic_a, topic_b = self._pair(topic_a, topic_b)
        row = postgres_client.fetch_one(
            """
            INSERT INTO duplicates(topic_a, topic_b, score, status)
            VALUES (%s, %s, %s, 'PENDING')
            ON CONFLICT (topic_a, topic_b) DO UPDATE
            SET score = duplicates.score
            RETURNING topic_a, topic_b, score, status, (xmax = 0) AS created
            """,
            (topic_a, topic_b, score),
        )
        return self._record(row), bool(row["created"])

    def add(self, item: dict) -> dict:
        topic_a, topic_b = self._pair(*item["topics"])
        row = postgres_client.fetch_one(
            """
            INSERT INTO duplicates(topic_a, topic_b, score, status)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (topic_a, topic_b) DO UPDATE
            SET score = EXCLUDED.score, updated_at = now()
            RETURNING topic_a, topic_b, score, status
            """,
            (topic_a, topic_b, item["score"], item["status"]),
        )
        return {
            "topics": [row["topic_a"], row["topic_b"]],
            "score": row["score"],
            "status": row["status"],
        }

    def update_status(self, topic_a: str, topic_b: str, status: str) -> dict | None:
        topic_a, topic_b = self._pair(topic_a, topic_b)
        row = postgres_client.fetch_one(
            """
            UPDATE duplicates SET status = %s, updated_at = now()
            WHERE topic_a = %s AND topic_b = %s
            RETURNING topic_a, topic_b, score, status
            """,
            (status, topic_a, topic_b),
        )
        if not row:
            return None
        return {
            "topics": [row["topic_a"], row["topic_b"]],
            "score": row["score"],
            "status": row["status"],
        }

    @staticmethod
    def _record(row) -> dict:
        return {
            "topics": [row["topic_a"], row["topic_b"]],
            "score": row["score"],
            "status": row["status"],
        }


class_store = ClassStore()
dupe_store = DupeStore()
