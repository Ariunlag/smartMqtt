"""Atomic duplicate identity confirmation and class-membership reconciliation."""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock

from services.store.canonical_identity_store import CanonicalIdentityStore
from services.store.relation_store import DupeStore


class DuplicateCanonicalizationConflict(ValueError):
    """A durable identity or class decision makes the merge unsafe."""


@dataclass(frozen=True, slots=True)
class DuplicateCanonicalizationResult:
    record: dict
    canonical_topic: str
    alias_topic: str
    invalidated_recommendation_count: int = 0


class DuplicateCanonicalizationService:
    """Resolve canonical identity without depending on recommendation runtime."""

    def __init__(
        self, identity_store: CanonicalIdentityStore, dupe_store: DupeStore
    ) -> None:
        self.identity_store = identity_store
        self.dupe_store = dupe_store
        self._lock = RLock()

    def confirm(
        self,
        topic_a: str,
        topic_b: str,
        alias_target: str,
        *,
        recommendation_application=None,
    ) -> DuplicateCanonicalizationResult | None:
        if alias_target not in {topic_a, topic_b}:
            raise ValueError("Unsubscribe target must be one of the duplicate topics")
        pair = self.dupe_store.get_pair(topic_a, topic_b)
        if pair is None:
            return None
        requested_canonical = topic_b if alias_target == topic_a else topic_a
        if pair["status"] == "NOT_DUPLICATE":
            raise DuplicateCanonicalizationConflict(
                "NOT_DUPLICATE is a terminal human decision"
            )
        if pair["status"] == "CONFIRMED_DUPLICATE":
            alias_identity = self.identity_store.get(alias_target)
            requested_root = self.identity_store.resolve_canonical(requested_canonical)
            if (
                alias_identity.is_alias
                and alias_identity.canonical_topic == requested_root
            ):
                if recommendation_application is not None:
                    recommendation_application.canonicalized(
                        requested_root, self._aliases_for_root(requested_root)
                    )
                return DuplicateCanonicalizationResult(
                    pair, requested_root, alias_target
                )
            raise DuplicateCanonicalizationConflict(
                "Confirmed duplicate has unresolved canonical identity"
            )

        with self._lock, self.identity_store.database.transaction() as conn:
            self._preflight_class_membership(conn, requested_canonical, alias_target)
            merge = self.identity_store.merge(conn, requested_canonical, alias_target)
            affected_class_names = self._classes_for_aliases(conn, merge.aliases)
            self._reconcile_relations(conn, merge.canonical_topic, merge.aliases)
            self._bump_class_profile_versions(conn, affected_class_names)
            pair_a, pair_b = sorted((topic_a, topic_b))
            row = conn.execute(
                """
                UPDATE duplicates
                SET status = 'CONFIRMED_DUPLICATE', updated_at = now()
                WHERE topic_a = %s AND topic_b = %s
                RETURNING topic_a, topic_b, score, status
                """,
                (pair_a, pair_b),
            ).fetchone()
            if row is None:
                raise RuntimeError("Duplicate pair disappeared during resolution")
            record = {
                "topics": [row["topic_a"], row["topic_b"]],
                "score": row["score"],
                "status": row["status"],
            }

        if recommendation_application is not None:
            # Durable audit first: a later derived-profile cleanup failure must not
            # erase the fact that the human duplicate decision committed.
            recommendation_application.metadata_store.audit(
                action_type="DUPLICATE_CONFIRM",
                details={
                    "canonical_topic": merge.canonical_topic,
                    "original_topic": alias_target,
                    "duplicate_state": "CONFIRMED_DUPLICATE",
                    "aliases": list(merge.aliases),
                },
            )
            # Derived pair/prototype cleanup is intentionally idempotent. If it
            # fails after the DB transaction, retrying the confirmed action runs
            # this reconciliation again without changing canonical identity.
            recommendation_application.canonicalized(
                merge.canonical_topic, merge.aliases
            )
        return DuplicateCanonicalizationResult(
            record=record,
            canonical_topic=merge.canonical_topic,
            alias_topic=alias_target,
        )

    def _aliases_for_root(self, canonical: str) -> tuple[str, ...]:
        rows = self.identity_store.database.fetch_all(
            """
            SELECT topic FROM duplicate_canonical_topics
            WHERE canonical_topic = %s AND topic <> %s
            ORDER BY topic
            """,
            (canonical, canonical),
        )
        return tuple(row["topic"] for row in rows)

    @staticmethod
    def _preflight_class_membership(conn, canonical: str, alias: str) -> None:
        rows = conn.execute(
            """
            SELECT topic, array_agg(class_name ORDER BY class_name) AS classes
            FROM class_topics WHERE topic = ANY(%s::text[])
            GROUP BY topic
            """,
            ([canonical, alias],),
        ).fetchall()
        memberships = {row["topic"]: tuple(row["classes"]) for row in rows}
        left = memberships.get(canonical, ())
        right = memberships.get(alias, ())
        if left and right and left != right:
            raise DuplicateCanonicalizationConflict(
                "Topics have conflicting explicit class memberships"
            )

    @staticmethod
    def _classes_for_aliases(conn, aliases: tuple[str, ...]) -> tuple[str, ...]:
        if not aliases:
            return ()
        rows = conn.execute(
            """
            SELECT DISTINCT class_name FROM class_topics
            WHERE topic = ANY(%s::text[])
            ORDER BY class_name
            """,
            (list(aliases),),
        ).fetchall()
        return tuple(row["class_name"] for row in rows)

    @staticmethod
    def _bump_class_profile_versions(conn, class_names: tuple[str, ...]) -> None:
        if not class_names:
            return
        conn.execute(
            """
            UPDATE classes SET profile_version = profile_version + 1
            WHERE name = ANY(%s::text[])
            """,
            (list(class_names),),
        )

    @staticmethod
    def _reconcile_relations(conn, canonical: str, aliases: tuple[str, ...]) -> None:
        """Move only active runtime relations to the canonical topic.

        Historical tag-group tables are intentionally retained by migrations for
        compatibility/research history, but the retired runtime no longer writes them.
        """
        for alias in aliases:
            conn.execute(
                """
                INSERT INTO class_topics(class_name, topic, position)
                SELECT class_name, %s, position FROM class_topics WHERE topic = %s
                ON CONFLICT (class_name, topic) DO UPDATE
                SET position = LEAST(class_topics.position, EXCLUDED.position)
                """,
                (canonical, alias),
            )
            conn.execute("DELETE FROM class_topics WHERE topic = %s", (alias,))
            conn.execute("DELETE FROM streams WHERE topic = %s", (alias,))
