"""In-memory diagnostic runtime for semantic candidate review."""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock

from .candidate_confirmation import CandidateIdentity
from .candidate_membership_review import CandidateMembershipReview
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


class PendingCandidateNotFoundError(LookupError):
    """Raised when a review targets an identity that is not pending."""


@dataclass(frozen=True, slots=True)
class PendingSemanticCandidate:
    """One pending discovery candidate keyed by durable content identity."""

    identity: CandidateIdentity
    candidate_index: int | None = None


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


class SemanticReviewRuntime:
    """Own isolated in-memory state used by the diagnostic review API."""

    def __init__(
        self,
        unknown_pool: UnknownStreamPool | None = None,
        evidence_store: TrustedClassEvidenceStore | None = None,
        constraint_store: NegativeMembershipConstraintStore | None = None,
        workflow: SemanticFeedbackWorkflow | None = None,
        known_class_registry: KnownClassRegistry | None = None,
        class_catalog: SemanticClassCatalog | None = None,
        assembler: KnownClassAssembler | None = None,
        feedback_lock=None,
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
        self.workflow = workflow or SemanticFeedbackWorkflow()
        self.known_class_registry = known_class_registry
        self.class_catalog = class_catalog
        self.assembler = assembler or KnownClassAssembler()
        self.feedback_lock = feedback_lock or RLock()
        self._pending: dict[CandidateIdentity, PendingSemanticCandidate] = {}
        self._suppressed: set[CandidateIdentity] = set()
        self._pending_lock = RLock()

    def register_unknown_entry(self, entry: UnknownStreamEntry) -> None:
        """Insert or replace UNKNOWN evidence for an integration caller."""
        self.unknown_pool.upsert(entry)

    def register_candidate(self, candidate: UnknownClusterCandidate) -> None:
        """Register a discovery candidate without exposing a public write API."""
        identity = CandidateIdentity.from_candidate(candidate)
        with self._pending_lock:
            self._pending[identity] = PendingSemanticCandidate(
                identity=identity,
                candidate_index=candidate.candidate_index,
            )

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
            self._pending = {
                identity: candidate
                for identity, candidate in pending.items()
                if identity not in self._suppressed
            }

    def clear_candidates(self) -> None:
        """Atomically remove every pending discovery candidate."""
        with self._pending_lock:
            self._pending = {}

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
        """Apply a valid pending review and remove its candidate on success."""
        with self._pending_lock:
            if review.identity not in self._pending:
                raise PendingCandidateNotFoundError("Candidate is not pending")

            if self.known_class_registry is None or self.class_catalog is None:
                workflow_result = self._apply_workflow(review)
                result = self._result(class_id, workflow_result, False)
                self._suppress_and_remove(review.identity)
                return result
            if not isinstance(class_id, str) or not class_id.strip():
                raise ValueError("class_id must be a non-empty string")

            with self.feedback_lock:
                evidence_before = self.evidence_store.snapshot()
                constraints_before = self.constraint_store.snapshot()
                catalog_before = self.class_catalog.snapshot()
                registry_before = self.known_class_registry.snapshot()
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
                    result = self._result(class_id, workflow_result, True)
                    self._suppress_and_remove(review.identity)
                    return result
                except Exception:
                    self.evidence_store.replace(evidence_before)
                    self.constraint_store.replace(constraints_before)
                    self.class_catalog.replace(catalog_before)
                    self.known_class_registry.replace(registry_before)
                    raise

    def _apply_workflow(
        self, review: CandidateMembershipReview
    ) -> SemanticFeedbackWorkflowResult:
        return self.workflow.apply_review(
            review,
            self.unknown_pool,
            self.evidence_store,
            self.constraint_store,
        )

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
            return self._pending.pop(identity, None)

    def _suppress_and_remove(self, identity: CandidateIdentity) -> None:
        self._suppressed.add(identity)
        self._pending.pop(identity, None)
