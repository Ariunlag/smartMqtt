"""Application-level composition of shared in-memory semantic runtime state."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from threading import RLock

from services.embedding.base_model import BaseEmbeddingModel

from .known_class_assembly import KnownClassAssembler
from .known_class_registry import (
    KnownClassRegistry,
    SemanticClassCatalog,
    SemanticClassDefinition,
)
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
from .semantic_processing_service import (
    SemanticProcessingConfig,
    SemanticProcessingService,
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
    known_class_registry: KnownClassRegistry
    class_catalog: SemanticClassCatalog
    processing_runtime: SemanticRuntimeOrchestrator
    processing_service: SemanticProcessingService
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
    known_class_registry: KnownClassRegistry | None = None,
    class_catalog: SemanticClassCatalog | None = None,
    known_class_assembler: KnownClassAssembler | None = None,
    feedback_lock=None,
    temporal_profiler: TemporalStreamProfiler | None = None,
    refresh_policy: SemanticRefreshPolicy | None = None,
    representation_builder: StabilityAwareRepresentationBuilder | None = None,
    class_scorer: RepresentationClassScorer | None = None,
    consensus_engine: MultiViewConsensusEngine | None = None,
    processing_service: SemanticProcessingService | None = None,
    processing_config: SemanticProcessingConfig | None = None,
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
    initial_known_classes = tuple(known_classes)
    shared_known_class_registry = (
        known_class_registry
        if known_class_registry is not None
        else KnownClassRegistry()
    )
    for known_class in initial_known_classes:
        shared_known_class_registry.upsert(known_class)
    shared_class_catalog = (
        class_catalog if class_catalog is not None else SemanticClassCatalog()
    )
    for known_class in shared_known_class_registry.snapshot():
        shared_class_catalog.register(
            SemanticClassDefinition(known_class.class_id, known_class.class_name)
        )
    shared_feedback_lock = feedback_lock or RLock()

    processing_runtime = SemanticRuntimeOrchestrator(
        embedding_model=embedding_model,
        known_class_registry=shared_known_class_registry,
        decision_policy=decision_policy,
        state_store=state_store,
        unknown_pool=shared_unknown_pool,
        constraint_store=shared_constraint_store,
        feedback_lock=shared_feedback_lock,
        temporal_profiler=temporal_profiler,
        refresh_policy=refresh_policy,
        representation_builder=representation_builder,
        class_scorer=class_scorer,
        consensus_engine=consensus_engine,
    )
    shared_processing_service = processing_service or SemanticProcessingService(
        processing_runtime,
        config=processing_config,
    )
    if shared_processing_service.runtime is not processing_runtime:
        raise ValueError("processing_service must reference the application runtime")
    review_runtime = SemanticReviewRuntime(
        unknown_pool=shared_unknown_pool,
        evidence_store=shared_evidence_store,
        constraint_store=shared_constraint_store,
        workflow=shared_feedback_workflow,
        known_class_registry=shared_known_class_registry,
        class_catalog=shared_class_catalog,
        assembler=known_class_assembler,
        feedback_lock=shared_feedback_lock,
    )
    return SemanticApplication(
        unknown_pool=shared_unknown_pool,
        evidence_store=shared_evidence_store,
        constraint_store=shared_constraint_store,
        feedback_workflow=shared_feedback_workflow,
        known_class_registry=shared_known_class_registry,
        class_catalog=shared_class_catalog,
        processing_runtime=processing_runtime,
        processing_service=shared_processing_service,
        review_runtime=review_runtime,
    )
