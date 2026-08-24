"""In-memory diagnostic runtime for semantic candidate review."""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass, replace
from threading import RLock
from typing import TYPE_CHECKING

from .candidate_confirmation import CandidateIdentity
from .candidate_membership_review import CandidateMembershipReview
from .confirmed_membership import (
    ConfirmedSemanticMembership,
    ConfirmedSemanticMembershipStore,
)
from .known_class_assembly import KnownClassAssembler, KnownClassAssemblyRequest
from .known_class_registry import (
    KnownClassRegistry,
    SemanticClassCatalog,
    SemanticClassDefinition,
)
from .semantic_feedback_workflow import (
    NegativeMembershipConstraintStore,
    SemanticFeedbackWorkflow,
    SemanticFeedbackWorkflowResult,
)
from .trusted_class_evidence import TrustedClassEvidenceStore
from .unknown_stream_discovery import (
    UnknownClusterCandidate,
    UnknownStreamDiscoveryResult,
)
from .unknown_stream_pool import UnknownStreamEntry, UnknownStreamPool

if TYPE_CHECKING:
    from collections.abc import Callable

    from .semantic_runtime import SemanticRuntimeOrchestrator


class PendingCandidateNotFoundError(LookupError):
    """Raised when a review targets an identity that is not pending."""


@dataclass(frozen=True, slots=True)
class PendingSemanticCandidate:
    """One pending discovery candidate keyed by durable content identity."""

    identity: CandidateIdentity
    candidate_index: int | None = None
    retained_after_review: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.retained_after_review, bool):
            raise TypeError("retained_after_review must be a boolean")


@dataclass(frozen=True, slots=True)
class PrototypeSummary:
    """Vector-free summary of one representation-specific prototype."""

    representation_name: str
    member_topics: tuple[str, ...]
    member_count: int


@dataclass(frozen=True, slots=True)
class SemanticReviewApplicationResult:
    """Workflow result plus safe summaries of all six prototypes."""

    class_id: str | None
    workflow: SemanticFeedbackWorkflowResult
    prototypes: tuple[PrototypeSummary, ...]
    registry_updated: bool


@dataclass(frozen=True, slots=True)
class SemanticReviewStateSnapshot:
    """Immutable pending and reviewed-candidate publication state."""

    pending_candidates: tuple[PendingSemanticCandidate, ...]
    suppressed_candidates: tuple[CandidateIdentity, ...]


class SemanticReviewRuntime:
    """Own isolated in-memory state used by the diagnostic review API."""

    def __init__(
        self,
        unknown_pool: UnknownStreamPool | None = None,
        evidence_store: TrustedClassEvidenceStore | None = None,
        constraint_store: NegativeMembershipConstraintStore | None = None,
        confirmed_membership_store: ConfirmedSemanticMembershipStore | None = None,
        processing_runtime: SemanticRuntimeOrchestrator | None = None,
        workflow: SemanticFeedbackWorkflow | None = None,
        known_class_registry: KnownClassRegistry | None = None,
        class_catalog: SemanticClassCatalog | None = None,
        assembler: KnownClassAssembler | None = None,
        feedback_lock=None,
        state_coordinator=None,
    ) -> None:
        self.unknown_pool = (
            unknown_pool if unknown_pool is not None else UnknownStreamPool()
        )
        self.evidence_store = (
            evidence_store
            if evidence_store is not None
            else TrustedClassEvidenceStore()
        )
        self.constraint_store = (
            constraint_store
            if constraint_store is not None
            else NegativeMembershipConstraintStore()
        )
        self.confirmed_membership_store = (
            confirmed_membership_store
            if confirmed_membership_store is not None
            else ConfirmedSemanticMembershipStore()
        )
        self.processing_runtime = processing_runtime
        self.workflow = workflow or SemanticFeedbackWorkflow()
        self.known_class_registry = known_class_registry
        self.class_catalog = class_catalog
        self.assembler = assembler or KnownClassAssembler()
        self.feedback_lock = feedback_lock or RLock()
        self.state_coordinator = state_coordinator
        self._pending: dict[CandidateIdentity, PendingSemanticCandidate] = {}
        self._suppressed: set[CandidateIdentity] = set()
        self._pending_lock = RLock()
        self._discovery_requester: Callable[[], bool] | None = None

    def set_discovery_requester(self, requester: Callable[[], bool]) -> None:
        """Attach the existing bounded discovery coordinator request hook."""
        self._discovery_requester = requester

    def register_unknown_entry(self, entry: UnknownStreamEntry) -> None:
        """Insert or replace UNKNOWN evidence for an integration caller."""
        self.unknown_pool.upsert(entry)

    def register_candidate(self, candidate: UnknownClusterCandidate) -> None:
        """Register a discovery candidate without exposing a public write API."""
        identity = CandidateIdentity.from_candidate(candidate)
        pending_candidate = PendingSemanticCandidate(
            identity=identity,
            candidate_index=candidate.candidate_index,
        )
        with self._pending_lock:
            previous = self._pending.get(identity)
            changed = previous != pending_candidate
            if changed:
                self._pending[identity] = pending_candidate
        if changed and self.state_coordinator is not None:
            self.state_coordinator.mark_changed()

    def replace_discovery(self, result: UnknownStreamDiscoveryResult) -> None:
        """Replace pending candidates with one complete discovery result."""
        pending: dict[CandidateIdentity, PendingSemanticCandidate] = {}
        for representation in result.representations:
            for candidate in representation.candidates:
                identity = CandidateIdentity.from_candidate(candidate)
                pending[identity] = PendingSemanticCandidate(
                    identity=identity,
                    candidate_index=candidate.candidate_index,
                )
        with self._pending_lock:
            replacement = {
                identity: candidate
                for identity, candidate in pending.items()
                if identity not in self._suppressed
            }
            retained = {
                identity: candidate
                for identity, candidate in self._pending.items()
                if candidate.retained_after_review
            }
            replacement = {
                **replacement,
                **{
                    identity: replace(
                        replacement.get(identity, candidate),
                        retained_after_review=True,
                    )
                    for identity, candidate in retained.items()
                },
            }
            if self._pending == replacement:
                return
            self._pending = replacement
        if self.state_coordinator is not None:
            self.state_coordinator.mark_changed()

    def clear_candidates(self) -> None:
        """Remove discovery candidates while preserving disjoint reviewed state."""
        with self._pending_lock:
            replacement = {
                identity: candidate
                for identity, candidate in self._pending.items()
                if candidate.retained_after_review
            }
            if self._pending == replacement:
                return
            self._pending = replacement
        if self.state_coordinator is not None:
            self.state_coordinator.mark_changed()

    def snapshot_review_state(self) -> SemanticReviewStateSnapshot:
        with self._pending_lock:
            return SemanticReviewStateSnapshot(
                pending_candidates=self.list_candidates(),
                suppressed_candidates=tuple(
                    sorted(
                        self._suppressed,
                        key=lambda identity: (
                            identity.representation_name,
                            identity.member_topics,
                        ),
                    )
                ),
            )

    def replace_review_state(self, snapshot: SemanticReviewStateSnapshot) -> None:
        pending = {item.identity: item for item in snapshot.pending_candidates}
        suppressed = set(snapshot.suppressed_candidates)
        if len(pending) != len(snapshot.pending_candidates):
            raise ValueError("Review snapshot contains duplicate pending identities")
        if len(suppressed) != len(snapshot.suppressed_candidates):
            raise ValueError("Review snapshot contains duplicate suppressed identities")
        if pending.keys() & suppressed:
            raise ValueError("A candidate cannot be both pending and suppressed")
        with self._pending_lock:
            if self._pending == pending and self._suppressed == suppressed:
                return
            self._pending = pending
            self._suppressed = suppressed
        if self.state_coordinator is not None:
            self.state_coordinator.mark_changed()

    def list_candidates(self) -> tuple[PendingSemanticCandidate, ...]:
        """Return candidates in deterministic identity order."""
        with self._pending_lock:
            return tuple(
                sorted(
                    self._pending.values(),
                    key=lambda candidate: (
                        candidate.identity.representation_name,
                        candidate.identity.member_topics,
                    ),
                )
            )

    def list_unknown_topics(self) -> tuple[str, ...]:
        """Return retained UNKNOWN topics in ascending order."""
        return tuple(entry.topic for entry in self.unknown_pool.all())

    def apply_review(
        self,
        review: CandidateMembershipReview,
        class_id: str | None = None,
    ) -> SemanticReviewApplicationResult:
        """Apply authoritative feedback and reconcile all shared state atomically."""
        transaction = (
            self.state_coordinator.transaction()
            if self.state_coordinator is not None
            else nullcontext()
        )
        result: SemanticReviewApplicationResult
        with self._pending_lock, self.feedback_lock, transaction:
            if review.identity not in self._pending:
                raise PendingCandidateNotFoundError("Candidate is not pending")

            if self.known_class_registry is None or self.class_catalog is None:
                workflow_result = self._apply_workflow(review)
                result = self._result(class_id, workflow_result, False)
                self._suppress_and_remove(review.identity)
                return result
            if not isinstance(class_id, str) or not class_id.strip():
                raise ValueError("class_id must be a non-empty string")

            evidence_before = self.evidence_store.snapshot()
            constraints_before = self.constraint_store.snapshot()
            memberships_before = self.confirmed_membership_store.snapshot()
            catalog_before = self.class_catalog.snapshot()
            registry_before = self.known_class_registry.snapshot()
            unknown_before = self.unknown_pool.snapshot()
            review_before = self.snapshot_review_state()
            runtime_before = (
                self.processing_runtime.state_store.snapshot()
                if self.processing_runtime is not None
                else ()
            )
            context_generation = (
                self.processing_runtime.semantic_context_generation
                if self.processing_runtime is not None
                else None
            )
            context_before = (
                context_generation.generation if context_generation is not None else 0
            )
            try:
                self.class_catalog.register(
                    SemanticClassDefinition(class_id, review.semantic_class_name)
                )
                workflow_result = self._apply_workflow(review)
                assembly = self.assembler.assemble(
                    KnownClassAssemblyRequest(class_id, review.semantic_class_name),
                    self.evidence_store,
                )
                if not assembly.is_complete:
                    missing = ", ".join(assembly.missing_representations)
                    raise ValueError(
                        f"Cannot publish incomplete known class '{class_id}'; "
                        f"missing representations: {missing}"
                    )
                self.known_class_registry.upsert(assembly.centroids)
                for topic in review.removed_topics:
                    existing = self.confirmed_membership_store.get(topic)
                    if (
                        existing is not None
                        and existing.class_id == class_id
                        and existing.semantic_class_name == review.semantic_class_name
                    ):
                        self.confirmed_membership_store.remove(topic)
                for topic in review.positive_topics:
                    self.confirmed_membership_store.upsert(
                        ConfirmedSemanticMembership(
                            topic=topic,
                            class_id=class_id,
                            semantic_class_name=review.semantic_class_name,
                        )
                    )
                for topic in review.positive_topics:
                    self.unknown_pool.remove(topic)
                if self.processing_runtime is not None:
                    self.processing_runtime.reconcile_context(
                        review.positive_topics + review.removed_topics,
                        coordinated=True,
                    )
                    self.processing_runtime.remove_stale_unknown_entries()
                self._invalidate_after_review(review)
                result = self._result(class_id, workflow_result, True)
            except Exception:
                restore_context = (
                    context_generation.restore(context_before)
                    if context_generation is not None
                    else nullcontext()
                )
                with restore_context:
                    self.evidence_store.replace(evidence_before)
                    self.constraint_store.replace(constraints_before)
                    self.confirmed_membership_store.replace(memberships_before)
                    self.class_catalog.replace(catalog_before)
                    self.known_class_registry.replace(registry_before)
                    self.unknown_pool.replace(
                        unknown_before.entries,
                        unknown_before.version,
                    )
                    self.replace_review_state(review_before)
                    if self.processing_runtime is not None:
                        self.processing_runtime.state_store.replace(runtime_before)
                raise
        if self._discovery_requester is not None:
            self._discovery_requester()
        return result

    def _apply_workflow(
        self, review: CandidateMembershipReview
    ) -> SemanticFeedbackWorkflowResult:
        args = (
            review,
            self.unknown_pool,
            self.evidence_store,
            self.constraint_store,
        )
        if self.processing_runtime is None:
            return self.workflow.apply_review(*args)
        return self.workflow.apply_review(*args, self._resolve_embeddings)

    def _resolve_embeddings(self, topic: str):
        entry = self.unknown_pool.get(topic)
        if entry is not None:
            return entry.embeddings
        if self.processing_runtime is None:
            return None
        state = self.processing_runtime.state_store.get(topic)
        return state.embeddings if state is not None else None

    @staticmethod
    def _result(
        class_id: str | None,
        workflow_result: SemanticFeedbackWorkflowResult,
        registry_updated: bool,
    ) -> SemanticReviewApplicationResult:
        return SemanticReviewApplicationResult(
            class_id=class_id,
            workflow=workflow_result,
            prototypes=tuple(
                PrototypeSummary(
                    representation_name=evidence.representation_name,
                    member_topics=evidence.member_topics,
                    member_count=evidence.member_count,
                )
                for evidence in workflow_result.prototype_evidence
            ),
            registry_updated=registry_updated,
        )

    def remove_candidate(
        self, identity: CandidateIdentity
    ) -> PendingSemanticCandidate | None:
        """Remove a pending candidate by durable content identity."""
        with self._pending_lock:
            removed = self._pending.pop(identity, None)
        if removed is not None and self.state_coordinator is not None:
            self.state_coordinator.mark_changed()
        return removed

    def invalidate_topics(
        self, topics: tuple[str, ...]
    ) -> tuple[PendingSemanticCandidate, ...]:
        """Remove every pending candidate containing an inactive topic."""
        invalid = set(topics)
        with self._pending_lock:
            removed = tuple(
                candidate
                for identity, candidate in self._pending.items()
                if invalid.intersection(identity.member_topics)
            )
            if not removed:
                return ()
            self._pending = {
                identity: candidate
                for identity, candidate in self._pending.items()
                if not invalid.intersection(identity.member_topics)
            }
        if self.state_coordinator is not None:
            self.state_coordinator.mark_changed()
        return removed

    def _suppress_and_remove(self, identity: CandidateIdentity) -> None:
        changed = identity not in self._suppressed or identity in self._pending
        self._suppressed.add(identity)
        self._pending.pop(identity, None)
        if changed and self.state_coordinator is not None:
            self.state_coordinator.mark_changed()

    def _invalidate_after_review(self, review: CandidateMembershipReview) -> None:
        """Suppress the reviewed identity and drop overlapping stale candidates."""
        positive = set(review.positive_topics)
        replacement = {
            identity: replace(candidate, retained_after_review=True)
            for identity, candidate in self._pending.items()
            if identity != review.identity
            and not (positive & set(identity.member_topics))
        }
        changed = (
            self._pending != replacement or review.identity not in self._suppressed
        )
        self._pending = replacement
        self._suppressed.add(review.identity)
        if changed and self.state_coordinator is not None:
            self.state_coordinator.mark_changed()
