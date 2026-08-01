"""Application-level composition of shared in-memory semantic runtime state."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from services.embedding.base_model import BaseEmbeddingModel

from .multi_view_consensus import MultiViewConsensusEngine
from .representation_class_scoring import (
    RepresentationClassCentroids,
    RepresentationClassScorer,
)
from .semantic_class_decision import SemanticClassDecisionPolicy
from .semantic_feedback_workflow import (
    NegativeMembershipConstraintStore,
    SemanticFeedbackWorkflow,
)
from .semantic_refresh import SemanticRefreshPolicy
from .semantic_review_runtime import SemanticReviewRuntime
from .semantic_runtime import SemanticRuntimeOrchestrator, SemanticRuntimeStateStore
from .stability_aware_representations import StabilityAwareRepresentationBuilder
from .temporal_profile import TemporalStreamProfiler
from .trusted_class_evidence import TrustedClassEvidenceStore
from .unknown_stream_pool import UnknownStreamPool


@dataclass(frozen=True, slots=True)
class SemanticApplication:
    """One isolated ownership boundary for processing and human review state."""

    unknown_pool: UnknownStreamPool
    evidence_store: TrustedClassEvidenceStore
    constraint_store: NegativeMembershipConstraintStore
    feedback_workflow: SemanticFeedbackWorkflow
    processing_runtime: SemanticRuntimeOrchestrator
    review_runtime: SemanticReviewRuntime


def build_semantic_application(
    *,
    embedding_model: BaseEmbeddingModel,
    known_classes: Iterable[RepresentationClassCentroids],
    decision_policy: SemanticClassDecisionPolicy,
    state_store: SemanticRuntimeStateStore | None = None,
    unknown_pool: UnknownStreamPool | None = None,
    evidence_store: TrustedClassEvidenceStore | None = None,
    constraint_store: NegativeMembershipConstraintStore | None = None,
    feedback_workflow: SemanticFeedbackWorkflow | None = None,
    temporal_profiler: TemporalStreamProfiler | None = None,
    refresh_policy: SemanticRefreshPolicy | None = None,
    representation_builder: StabilityAwareRepresentationBuilder | None = None,
    class_scorer: RepresentationClassScorer | None = None,
    consensus_engine: MultiViewConsensusEngine | None = None,
) -> SemanticApplication:
    """Build both runtimes around the exact same injected state objects."""
    shared_unknown_pool = (
        unknown_pool if unknown_pool is not None else UnknownStreamPool()
    )
    shared_evidence_store = (
        evidence_store if evidence_store is not None else TrustedClassEvidenceStore()
    )
    shared_constraint_store = (
        constraint_store
        if constraint_store is not None
        else NegativeMembershipConstraintStore()
    )
    shared_feedback_workflow = (
        feedback_workflow
        if feedback_workflow is not None
        else SemanticFeedbackWorkflow()
    )

    processing_runtime = SemanticRuntimeOrchestrator(
        embedding_model=embedding_model,
        known_classes=known_classes,
        decision_policy=decision_policy,
        state_store=state_store,
        unknown_pool=shared_unknown_pool,
        temporal_profiler=temporal_profiler,
        refresh_policy=refresh_policy,
        representation_builder=representation_builder,
        class_scorer=class_scorer,
        consensus_engine=consensus_engine,
    )
    review_runtime = SemanticReviewRuntime(
        unknown_pool=shared_unknown_pool,
        evidence_store=shared_evidence_store,
        constraint_store=shared_constraint_store,
        workflow=shared_feedback_workflow,
    )
    return SemanticApplication(
        unknown_pool=shared_unknown_pool,
        evidence_store=shared_evidence_store,
        constraint_store=shared_constraint_store,
        feedback_workflow=shared_feedback_workflow,
        processing_runtime=processing_runtime,
        review_runtime=review_runtime,
    )
