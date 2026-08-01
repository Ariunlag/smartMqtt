"""In-memory diagnostic runtime for semantic candidate review."""

from __future__ import annotations

from dataclasses import dataclass

from .candidate_confirmation import CandidateIdentity
from .candidate_membership_review import CandidateMembershipReview
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

    workflow: SemanticFeedbackWorkflowResult
    prototypes: tuple[PrototypeSummary, ...]


class SemanticReviewRuntime:
    """Own isolated in-memory state used by the diagnostic review API."""

    def __init__(
        self,
        unknown_pool: UnknownStreamPool | None = None,
        evidence_store: TrustedClassEvidenceStore | None = None,
        constraint_store: NegativeMembershipConstraintStore | None = None,
        workflow: SemanticFeedbackWorkflow | None = None,
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
        self._pending: dict[CandidateIdentity, PendingSemanticCandidate] = {}

    def register_unknown_entry(self, entry: UnknownStreamEntry) -> None:
        """Insert or replace UNKNOWN evidence for an integration caller."""
        self.unknown_pool.upsert(entry)

    def register_candidate(self, candidate: UnknownClusterCandidate) -> None:
        """Register a discovery candidate without exposing a public write API."""
        identity = CandidateIdentity.from_candidate(candidate)
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
        self._pending = pending

    def list_candidates(self) -> tuple[PendingSemanticCandidate, ...]:
        """Return candidates in deterministic identity order."""
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
        self, review: CandidateMembershipReview
    ) -> SemanticReviewApplicationResult:
        """Apply a valid pending review and remove its candidate on success."""
        if review.identity not in self._pending:
            raise PendingCandidateNotFoundError("Candidate is not pending")

        workflow_result = self.workflow.apply_review(
            review,
            self.unknown_pool,
            self.evidence_store,
            self.constraint_store,
        )
        prototypes = tuple(
            PrototypeSummary(
                representation_name=evidence.representation_name,
                member_topics=evidence.member_topics,
                member_count=evidence.member_count,
            )
            for evidence in workflow_result.prototype_evidence
        )
        self.remove_candidate(review.identity)
        return SemanticReviewApplicationResult(
            workflow=workflow_result,
            prototypes=prototypes,
        )

    def remove_candidate(
        self, identity: CandidateIdentity
    ) -> PendingSemanticCandidate | None:
        """Remove a pending candidate by durable content identity."""
        return self._pending.pop(identity, None)
