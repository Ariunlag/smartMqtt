from services.database.postgres import postgres_client


class TopicStore:
    table = "streams"

    def get_all(self) -> list[str]:
        rows = postgres_client.fetch_all(
            "SELECT topic FROM streams WHERE enabled = TRUE ORDER BY topic"
        )
        return [row["topic"] for row in rows]

    def add(self, topic: str) -> str:
        postgres_client.execute(
            """
            INSERT INTO streams(topic, enabled) VALUES (%s, TRUE)
            ON CONFLICT (topic) DO UPDATE SET enabled = TRUE
            """,
            (topic,),
        )
        return topic

    def remove(self, topic: str) -> bool:
        return postgres_client.execute(
            "DELETE FROM streams WHERE topic = %s",
            (topic,),
        ) > 0


class SimpleTopicStore:
    def __init__(self, table: str):
        if table not in {"ignored_topics", "detected_topics"}:
            raise ValueError("Unsupported topic table")
        self.table = table

    def get_all(self) -> list[str]:
        rows = postgres_client.fetch_all(
            f"SELECT topic FROM {self.table} ORDER BY topic"
        )
        return [row["topic"] for row in rows]

    def contains(self, topic: str) -> bool:
        row = postgres_client.fetch_one(
            f"SELECT EXISTS(SELECT 1 FROM {self.table} WHERE topic = %s) AS found",
            (topic,),
        )
        return bool(row and row["found"])

    def add(self, topic: str) -> str:
        postgres_client.execute(
            f"INSERT INTO {self.table}(topic) VALUES (%s) ON CONFLICT DO NOTHING",
            (topic,),
        )
        return topic

    def remove(self, topic: str) -> bool:
        return postgres_client.execute(
            f"DELETE FROM {self.table} WHERE topic = %s",
            (topic,),
        ) > 0


topic_store = TopicStore()
ignored_topic_store = SimpleTopicStore("ignored_topics")
detected_topic_store = SimpleTopicStore("detected_topics")
