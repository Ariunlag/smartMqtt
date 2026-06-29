from services.database.postgres import postgres_client


class ClassStore:
    def get_all(self) -> list[dict]:
        rows = postgres_client.fetch_all(
            """
            SELECT c.name, COALESCE(
                array_agg(ct.topic ORDER BY ct.position)
                    FILTER (WHERE ct.topic IS NOT NULL),
                ARRAY[]::text[]
            ) AS topics
            FROM classes c
            LEFT JOIN class_topics ct ON ct.class_name = c.name
            GROUP BY c.name
            ORDER BY c.name
            """
        )
        return [{"name": row["name"], "topics": row["topics"]} for row in rows]

    def add(self, item: dict) -> dict:
        topics = list(dict.fromkeys(item["topics"]))
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
        topics = list(dict.fromkeys(topics))
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
        return postgres_client.execute(
            "DELETE FROM classes WHERE name = %s",
            (name,),
        ) > 0


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


class_store = ClassStore()
dupe_store = DupeStore()
