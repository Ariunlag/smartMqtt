"""Atomic application of reviewed prototype and negative membership feedback."""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import TYPE_CHECKING

from .candidate_membership_review import CandidateMembershipReview
from .multi_view_consensus import RepresentationClassConsensus
from .reviewed_prototype_reconciliation import ReviewedPrototypeReconciler
from .trusted_class_evidence import TrustedClassEvidence, TrustedClassEvidenceStore
from .unknown_stream_pool import UnknownStreamPool

if TYPE_CHECKING:
    from collections.abc import Callable

    from .representation_embedder import RepresentationEmbeddings


@dataclass(frozen=True, slots=True)
class NegativeMembershipConstraint:
    """Class-wide exclusion for one topic until matching positive feedback."""

    topic: str
    semantic_class_name: str

    def __post_init__(self) -> None:
        if not isinstance(self.topic, str) or not self.topic.strip():
            raise ValueError("topic must be a non-empty string")
        if (
            not isinstance(self.semantic_class_name, str)
            or not self.semantic_class_name.strip()
        ):
            raise ValueError("semantic_class_name must be a non-empty string")


class NegativeMembershipConstraintStore:
    """Latest class-wide negative membership constraints."""

    def __init__(self, coordinator=None) -> None:
        self._constraints: dict[tuple[str, str], NegativeMembershipConstraint] = {}
        self._lock = RLock()
        self._coordinator = coordinator

    def upsert(self, constraint: NegativeMembershipConstraint) -> None:
        with self._lock:
            key = self._key(constraint.topic, constraint.semantic_class_name)
            if self._constraints.get(key) == constraint:
                return
            self._constraints[key] = constraint
        if self._coordinator is not None:
            self._coordinator.mark_changed()

    def get(
        self,
        topic: str,
        semantic_class_name: str,
    ) -> NegativeMembershipConstraint | None:
        with self._lock:
            return self._constraints.get(self._key(topic, semantic_class_name))

    def remove(
        self,
        topic: str,
        semantic_class_name: str,
    ) -> NegativeMembershipConstraint | None:
        with self._lock:
            removed = self._constraints.pop(self._key(topic, semantic_class_name), None)
        if removed is not None and self._coordinator is not None:
            self._coordinator.mark_changed()
        return removed

    def all(self) -> tuple[NegativeMembershipConstraint, ...]:
        with self._lock:
            return tuple(
                sorted(
                    self._constraints.values(),
                    key=lambda item: (item.semantic_class_name, item.topic),
                )
            )

    def snapshot(self) -> tuple[NegativeMembershipConstraint, ...]:
        return self.all()

    def replace(self, constraints: tuple[NegativeMembershipConstraint, ...]) -> None:
        replacement = {
            self._key(item.topic, item.semantic_class_name): item
            for item in constraints
        }
        if len(replacement) != len(constraints):
            raise ValueError("Constraint snapshot contains duplicates")
        with self._lock:
            if self._constraints == replacement:
                return
            self._constraints = replacement
        if self._coordinator is not None:
            self._coordinator.mark_changed()

    def __len__(self) -> int:
        with self._lock:
            return len(self._constraints)

    def is_blocked(self, topic: str, semantic_class_name: str) -> bool:
        """Return whether one class is ineligible for the topic."""
        return self.get(topic, semantic_class_name) is not None

    def filter_allowed(
        self,
        topic: str,
        candidates: tuple[RepresentationClassConsensus, ...],
    ) -> tuple[RepresentationClassConsensus, ...]:
        """Remove blocked classes without changing evidence or order."""
        with self._lock:
            return tuple(
                candidate
                for candidate in candidates
                if self._key(topic, candidate.class_name) not in self._constraints
            )

    @staticmethod
    def _key(topic: str, semantic_class_name: str) -> tuple[str, str]:
        return topic, semantic_class_name


@dataclass(frozen=True, slots=True)
class SemanticFeedbackWorkflowResult:
    """Deterministic outcome of atomically applied membership feedback."""

    semantic_class_name: str
    positive_topics: tuple[str, ...]
    removed_topics: tuple[str, ...]
    prototype_evidence: tuple[TrustedClassEvidence, ...]
    changed_representations: tuple[str, ...]
    constraints_added: tuple[NegativeMembershipConstraint, ...]
    constraints_removed: tuple[NegativeMembershipConstraint, ...]


class SemanticFeedbackWorkflow:
    """Coordinate prototype reconciliation and class-wide constraints."""

    def __init__(self, reconciler: ReviewedPrototypeReconciler | None = None) -> None:
        self.reconciler = reconciler or ReviewedPrototypeReconciler()

    def apply_review(
        self,
        review: CandidateMembershipReview,
        unknown_pool: UnknownStreamPool,
        evidence_store: TrustedClassEvidenceStore,
        constraint_store: NegativeMembershipConstraintStore,
        embedding_resolver: Callable[[str], RepresentationEmbeddings | None]
        | None = None,
    ) -> SemanticFeedbackWorkflowResult:
        """Prepare every change before committing either store."""
        reconciliation = self.reconciler.prepare(
            review,
            unknown_pool,
            evidence_store,
            embedding_resolver,
        )
        constraints_added = tuple(
            constraint
            for topic in review.removed_topics
            if constraint_store.get(topic, review.semantic_class_name)
            != (
                constraint := NegativeMembershipConstraint(
                    topic, review.semantic_class_name
                )
            )
        )
        constraints_removed = tuple(
            existing
            for topic in review.positive_topics
            if (existing := constraint_store.get(topic, review.semantic_class_name))
            is not None
        )

        changed = set(reconciliation.changed_representations)
        for evidence in reconciliation.evidence:
            if evidence.representation_name in changed:
                evidence_store.upsert(evidence)
        for constraint in constraints_removed:
            constraint_store.remove(
                constraint.topic,
                constraint.semantic_class_name,
            )
        for constraint in constraints_added:
            constraint_store.upsert(constraint)

        return SemanticFeedbackWorkflowResult(
            semantic_class_name=review.semantic_class_name,
            positive_topics=review.positive_topics,
            removed_topics=review.removed_topics,
            prototype_evidence=reconciliation.evidence,
            changed_representations=reconciliation.changed_representations,
            constraints_added=constraints_added,
            constraints_removed=constraints_removed,
        )
