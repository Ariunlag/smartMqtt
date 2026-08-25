"""Atomic duplicate confirmation and downstream canonical reconciliation."""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
from threading import RLock
from typing import TYPE_CHECKING

from services.store.canonical_identity_store import CanonicalIdentityStore
from services.store.relation_store import DupeStore

if TYPE_CHECKING:
    from services.semantic.semantic_application import SemanticApplication


class DuplicateCanonicalizationConflict(ValueError):
    """A human semantic decision makes the identity merge unsafe."""


@dataclass(frozen=True, slots=True)
class DuplicateCanonicalizationResult:
    record: dict
    canonical_topic: str
    alias_topic: str
    invalidated_candidate_count: int


class DuplicateCanonicalizationService:
    """Resolve identity and reconcile active recommendation state together."""

    def __init__(
        self,
        identity_store: CanonicalIdentityStore,
        dupe_store: DupeStore,
    ) -> None:
        self.identity_store = identity_store
        self.dupe_store = dupe_store
        self._lock = RLock()

    def confirm(
        self,
        application: SemanticApplication,
        topic_a: str,
        topic_b: str,
        alias_target: str,
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
                return DuplicateCanonicalizationResult(
                    pair, requested_root, alias_target, 0
                )
            raise DuplicateCanonicalizationConflict(
                "Legacy confirmed duplicate has unresolved canonical identity; "
                "its unsubscribe target was not recorded"
            )

        with self._lock, application.review_runtime.feedback_lock:
            semantic_before = application.snapshot()
            context = (
                application.state_coordinator.transaction()
                if application.state_coordinator is not None
                else nullcontext()
            )
            try:
                with self.identity_store.database.transaction() as conn, context:
                    merge = self.identity_store.merge(
                        conn, requested_canonical, alias_target
                    )
                    canonical = merge.canonical_topic
                    aliases = merge.aliases
                    self._preflight_semantics(application, canonical, aliases)
                    self._reconcile_relations(conn, canonical, aliases)
                    invalidated = self._reconcile_semantics(
                        application, canonical, aliases
                    )
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
                        raise RuntimeError(
                            "Duplicate pair disappeared during resolution"
                        )
                    record = {
                        "topics": [row["topic_a"], row["topic_b"]],
                        "score": row["score"],
                        "status": row["status"],
                    }
            except Exception:
                application.restore(semantic_before)
                raise

        application.discovery_service.request()
        return DuplicateCanonicalizationResult(
            record=record,
            canonical_topic=canonical,
            alias_topic=alias_target,
            invalidated_candidate_count=len(invalidated),
        )

    @staticmethod
    def _preflight_semantics(
        application, canonical: str, aliases: tuple[str, ...]
    ) -> None:
        memberships = [
            membership
            for topic in (canonical, *aliases)
            if (membership := application.confirmed_membership_store.get(topic))
            is not None
        ]
        identities = {(m.class_id, m.semantic_class_name) for m in memberships}
        if len(identities) > 1:
            detail = ", ".join(
                f"{m.topic}={m.semantic_class_name}" for m in memberships
            )
            raise DuplicateCanonicalizationConflict(
                f"Conflicting human-confirmed semantic memberships: {detail}"
            )
        if memberships:
            positive = memberships[0].semantic_class_name
            conflicting = [
                constraint.topic
                for constraint in application.constraint_store.all()
                if constraint.topic in {canonical, *aliases}
                and constraint.semantic_class_name == positive
            ]
            if conflicting:
                raise DuplicateCanonicalizationConflict(
                    "Negative semantic feedback conflicts with authoritative "
                    f"membership '{positive}' for: {', '.join(sorted(conflicting))}"
                )

    @staticmethod
    def _reconcile_relations(conn, canonical: str, aliases: tuple[str, ...]) -> None:
        for alias in aliases:
            conn.execute(
                """
                INSERT INTO tag_group_topics(group_id, topic)
                SELECT group_id, %s FROM tag_group_topics WHERE topic = %s
                ON CONFLICT DO NOTHING
                """,
                (canonical, alias),
            )
            conn.execute("DELETE FROM tag_group_topics WHERE topic = %s", (alias,))
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

    def _reconcile_semantics(
        self, application, canonical: str, aliases: tuple[str, ...]
    ):
        from services.semantic.confirmed_membership import (
            ConfirmedSemanticMembership,
        )
        from services.semantic.known_class_assembly import KnownClassAssemblyRequest
        from services.semantic.semantic_feedback_workflow import (
            NegativeMembershipConstraint,
        )

        topic_set = {canonical, *aliases}
        memberships = [
            membership
            for topic in sorted(topic_set)
            if (membership := application.confirmed_membership_store.get(topic))
            is not None
        ]
        positive = memberships[0] if memberships else None
        constraints = tuple(
            item for item in application.constraint_store.all() if item.topic in aliases
        )

        replacements = self._prepare_evidence(application, canonical, aliases)
        for alias in aliases:
            application.processing_runtime.state_store.remove(alias)
            application.unknown_pool.remove(alias)
            application.confirmed_membership_store.remove(alias)
            for constraint in tuple(application.constraint_store.all()):
                if constraint.topic == alias:
                    application.constraint_store.remove(
                        alias, constraint.semantic_class_name
                    )
        for constraint in constraints:
            application.constraint_store.upsert(
                NegativeMembershipConstraint(canonical, constraint.semantic_class_name)
            )
        if positive is not None:
            application.confirmed_membership_store.upsert(
                ConfirmedSemanticMembership(
                    canonical, positive.class_id, positive.semantic_class_name
                )
            )
            application.unknown_pool.remove(canonical)
        for evidence in replacements:
            application.evidence_store.upsert(evidence)
        affected_names = tuple(
            sorted({item.semantic_class_name for item in replacements})
        )
        for class_name in affected_names:
            definition = application.class_catalog.get_by_name(class_name)
            if definition is None:
                continue
            assembly = application.review_runtime.assembler.assemble(
                KnownClassAssemblyRequest(definition.class_id, class_name),
                application.evidence_store,
            )
            if assembly.is_complete:
                application.known_class_registry.upsert(assembly.centroids)
        invalidated = application.review_runtime.invalidate_topics(aliases)
        application.processing_runtime.reconcile_context((canonical,), coordinated=True)
        application.processing_runtime.remove_stale_unknown_entries()
        return invalidated

    @staticmethod
    def _prepare_evidence(application, canonical: str, aliases: tuple[str, ...]):
        from services.semantic.stream_class import StreamClassEngine
        from services.semantic.trusted_class_evidence import TrustedClassEvidence

        replacements = []
        alias_set = set(aliases)
        for existing in application.evidence_store.all():
            members = set(existing.member_topics)
            if not members.intersection(alias_set):
                continue
            final = tuple(sorted((members - alias_set) | {canonical}))
            if len(final) == len(existing.member_topics):
                replacements.append(
                    TrustedClassEvidence(
                        existing.semantic_class_name,
                        existing.representation_name,
                        existing.centroid,
                        final,
                    )
                )
                continue
            vectors = []
            for topic in final:
                state = application.processing_runtime.state_store.get(topic)
                if state is None and topic == canonical:
                    state = next(
                        (
                            application.processing_runtime.state_store.get(alias)
                            for alias in aliases
                            if application.processing_runtime.state_store.get(alias)
                            is not None
                        ),
                        None,
                    )
                if state is not None:
                    embeddings = state.embeddings
                else:
                    unknown = application.unknown_pool.get(topic)
                    embeddings = unknown.embeddings if unknown is not None else None
                if embeddings is None:
                    raise DuplicateCanonicalizationConflict(
                        f"Missing cached embeddings needed to deduplicate prototype "
                        f"'{existing.semantic_class_name}'"
                    )
                vectors.append(getattr(embeddings, existing.representation_name))
            replacements.append(
                TrustedClassEvidence(
                    existing.semantic_class_name,
                    existing.representation_name,
                    StreamClassEngine.compute_centroid(vectors),
                    final,
                )
            )
        return tuple(replacements)
