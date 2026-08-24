"""Durable current identity for canonical topics and duplicate aliases."""

from __future__ import annotations

from dataclasses import dataclass

from services.database.postgres import postgres_client


@dataclass(frozen=True, slots=True)
class CanonicalIdentity:
    topic: str
    canonical_topic: str

    @property
    def is_alias(self) -> bool:
        return self.topic != self.canonical_topic


@dataclass(frozen=True, slots=True)
class CanonicalMerge:
    canonical_topic: str
    aliases: tuple[str, ...]


class CanonicalIdentityStore:
    """Resolve topics to direct roots; alias chains are never persisted."""

    def __init__(self, database=postgres_client) -> None:
        self.database = database

    def get(self, topic: str) -> CanonicalIdentity:
        row = self.database.fetch_one(
            "SELECT topic, canonical_topic FROM duplicate_canonical_topics WHERE topic = %s",
            (topic,),
        )
        return CanonicalIdentity(topic, row["canonical_topic"] if row else topic)

    def resolve_canonical(self, topic: str) -> str:
        return self.get(topic).canonical_topic

    canonical_topic = resolve_canonical

    def is_duplicate_alias(self, topic: str) -> bool:
        return self.get(topic).is_alias

    def is_active(self, topic: str) -> bool:
        return not self.is_duplicate_alias(topic)

    def resolve_many(self, topics: list[str] | tuple[str, ...]) -> dict[str, str]:
        unique = tuple(sorted(set(topics)))
        if not unique:
            return {}
        rows = self.database.fetch_all(
            """
            SELECT requested.topic,
                   COALESCE(identity.canonical_topic, requested.topic) AS canonical_topic
            FROM unnest(%s::text[]) AS requested(topic)
            LEFT JOIN duplicate_canonical_topics identity
                ON identity.topic = requested.topic
            """,
            (list(unique),),
        )
        return {row["topic"]: row["canonical_topic"] for row in rows}

    def merge(self, conn, canonical_topic: str, alias_topic: str) -> CanonicalMerge:
        """Merge two roots and directly re-parent the losing set."""
        if canonical_topic == alias_topic:
            raise ValueError("Duplicate topics must be different")
        first, second = sorted((canonical_topic, alias_topic))
        lock_key = f"{len(first)}:{first}{len(second)}:{second}"
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (lock_key,),
        )
        rows = conn.execute(
            """
            SELECT topic, canonical_topic FROM duplicate_canonical_topics
            WHERE topic = ANY(%s::text[]) FOR UPDATE
            """,
            ([canonical_topic, alias_topic],),
        ).fetchall()
        roots = {row["topic"]: row["canonical_topic"] for row in rows}
        winning_root = roots.get(canonical_topic, canonical_topic)
        losing_root = roots.get(alias_topic, alias_topic)
        if winning_root == losing_root:
            return CanonicalMerge(winning_root, ())
        locked = conn.execute(
            """
            SELECT topic, canonical_topic FROM duplicate_canonical_topics
            WHERE canonical_topic = ANY(%s::text[]) FOR UPDATE
            """,
            ([winning_root, losing_root],),
        ).fetchall()
        losing_topics = {
            row["topic"] for row in locked if row["canonical_topic"] == losing_root
        }
        # The root can be absent before first confirmation.
        losing_topics.add(losing_root)
        conn.execute(
            """
            INSERT INTO duplicate_canonical_topics(topic, canonical_topic)
            VALUES (%s, %s), (%s, %s)
            ON CONFLICT (topic) DO NOTHING
            """,
            (winning_root, winning_root, losing_root, losing_root),
        )
        conn.execute(
            """
            UPDATE duplicate_canonical_topics
            SET canonical_topic = %s, updated_at = now()
            WHERE canonical_topic = %s
            """,
            (winning_root, losing_root),
        )
        return CanonicalMerge(winning_root, tuple(sorted(losing_topics)))

    def legacy_unresolved_confirmations(self) -> list[dict]:
        """Return pre-migration confirmations whose target was never recorded."""
        rows = self.database.fetch_all(
            """
            SELECT d.topic_a, d.topic_b FROM duplicates d
            WHERE d.status = 'CONFIRMED_DUPLICATE'
              AND NOT EXISTS (
                SELECT 1
                FROM duplicate_canonical_topics topic_a_identity
                JOIN duplicate_canonical_topics topic_b_identity
                  ON topic_b_identity.canonical_topic =
                     topic_a_identity.canonical_topic
                WHERE topic_a_identity.topic = d.topic_a
                  AND topic_b_identity.topic = d.topic_b
                  AND (
                    topic_a_identity.topic <>
                        topic_a_identity.canonical_topic
                    OR topic_b_identity.topic <>
                        topic_b_identity.canonical_topic
                  )
              )
            ORDER BY d.topic_a, d.topic_b
            """
        )
        return [{"topics": [row["topic_a"], row["topic_b"]]} for row in rows]


canonical_identity_store = CanonicalIdentityStore()
