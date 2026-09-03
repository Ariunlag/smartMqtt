import uuid

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
            SELECT c.class_id, c.name, c.profile_version, COALESCE(
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
        return [
            {
                "class_id": row["class_id"],
                "name": row["name"],
                "topics": row["topics"],
                "profile_version": row["profile_version"],
            }
            for row in rows
        ]

    def get(self, name: str) -> dict | None:
        return next((item for item in self.get_all() if item["name"] == name), None)

    def get_by_id(self, class_id: str) -> dict | None:
        return next(
            (item for item in self.get_all() if item["class_id"] == class_id), None
        )

    def classes_for_topic(self, topic: str) -> list[dict]:
        canonical = self.identity_store.resolve_canonical(topic)
        return [item for item in self.get_all() if canonical in item["topics"]]

    def add(self, item: dict) -> dict:
        topics = self._canonicalize(item["topics"])
        class_id = item.get("class_id") or str(uuid.uuid4())
        with postgres_client.transaction() as conn:
            conn.execute(
                "INSERT INTO classes(name, class_id) VALUES (%s, %s)",
                (item["name"], class_id),
            )
            for position, topic in enumerate(topics):
                conn.execute(
                    """
                    INSERT INTO class_topics(class_name, topic, position)
                    VALUES (%s, %s, %s)
                    """,
                    (item["name"], topic, position),
                )
        return {
            "class_id": class_id,
            "name": item["name"],
            "topics": topics,
            "profile_version": 1,
        }

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
            row = conn.execute(
                """
                UPDATE classes SET profile_version = profile_version + 1
                WHERE name = %s
                RETURNING class_id, profile_version
                """,
                (name,),
            ).fetchone()
        return {
            "class_id": row["class_id"],
            "name": name,
            "topics": topics,
            "profile_version": row["profile_version"],
        }

    def bump_profile_version(self, name: str) -> int:
        row = postgres_client.fetch_one(
            """
            UPDATE classes SET profile_version = profile_version + 1
            WHERE name = %s RETURNING profile_version
            """,
            (name,),
        )
        if row is None:
            raise ValueError(f"Class '{name}' not found")
        return int(row["profile_version"])

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
        # Match PostgreSQL COLLATE "C" ordering used by the schema constraint.
        # UTF-8 byte ordering is deterministic and locale-independent.
        return tuple(sorted((topic_a, topic_b), key=lambda value: value.encode("utf-8")))

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

    def has_pending(self, topic: str) -> bool:
        return self.database_has_pending(topic)

    def pending_topics(self, topics: list[str] | tuple[str, ...]) -> set[str]:
        """Return requested topics participating in any pending duplicate pair."""
        selected = tuple(sorted(set(topics)))
        if not selected:
            return set()
        rows = postgres_client.fetch_all(
            """
            SELECT topic_a, topic_b FROM duplicates
            WHERE status = 'PENDING'
              AND (topic_a = ANY(%s::text[]) OR topic_b = ANY(%s::text[]))
            """,
            (list(selected), list(selected)),
        )
        requested = set(selected)
        pending: set[str] = set()
        for row in rows:
            if row["topic_a"] in requested:
                pending.add(row["topic_a"])
            if row["topic_b"] in requested:
                pending.add(row["topic_b"])
        return pending

    @staticmethod
    def database_has_pending(topic: str) -> bool:
        row = postgres_client.fetch_one(
            """
            SELECT 1 FROM duplicates
            WHERE status = 'PENDING' AND (topic_a = %s OR topic_b = %s)
            LIMIT 1
            """,
            (topic, topic),
        )
        return row is not None

    @staticmethod
    def _record(row) -> dict:
        return {
            "topics": [row["topic_a"], row["topic_b"]],
            "score": row["score"],
            "status": row["status"],
        }


class_store = ClassStore()
dupe_store = DupeStore()
