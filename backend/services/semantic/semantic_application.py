"""Application-level composition of shared in-memory semantic runtime state."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from threading import RLock

from services.embedding.base_model import BaseEmbeddingModel

from .confirmed_membership import ConfirmedSemanticMembershipStore
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
from .semantic_context import SemanticContextGeneration
from .semantic_discovery_service import (
    SemanticDiscoveryConfig,
    SemanticDiscoveryService,
)
from .semantic_feedback_workflow import (
    NegativeMembershipConstraintStore,
    SemanticFeedbackWorkflow,
)
from .semantic_persistence import (
    InMemorySemanticStateRepository,
    PostgresSemanticStateRepository,
    SemanticSnapshotSerializer,
    SemanticStateRepository,
    create_model_fingerprint,
)
from .semantic_persistence_service import (
    SemanticPersistenceConfig,
    SemanticPersistenceService,
)
from .semantic_processing_service import (
    SemanticProcessingConfig,
    SemanticProcessingService,
)
from .semantic_refresh import SemanticRefreshPolicy
from .semantic_review_runtime import SemanticReviewRuntime
from .semantic_runtime import SemanticRuntimeOrchestrator, SemanticRuntimeStateStore
from .semantic_state import (
    SEMANTIC_REPRESENTATION_CONTRACT_VERSION,
    SEMANTIC_STATE_SCHEMA_VERSION,
    SemanticApplicationSnapshot,
    SemanticPersistenceMetadata,
    SemanticStateCoordinator,
)
from .stability_aware_representations import StabilityAwareRepresentationBuilder
from .temporal_profile import TemporalStreamProfiler
from .trusted_class_evidence import TrustedClassEvidenceStore
from .unknown_stream_discovery import (
    HDBSCANDiscoveryConfig,
    UnknownStreamDiscoveryEngine,
)
from .unknown_stream_pool import UnknownStreamPool


@dataclass(frozen=True, slots=True)
class SemanticApplication:
    """One isolated ownership boundary for processing and human review state."""

    unknown_pool: UnknownStreamPool
    evidence_store: TrustedClassEvidenceStore
    constraint_store: NegativeMembershipConstraintStore
    confirmed_membership_store: ConfirmedSemanticMembershipStore
    feedback_workflow: SemanticFeedbackWorkflow
    known_class_registry: KnownClassRegistry
    class_catalog: SemanticClassCatalog
    processing_runtime: SemanticRuntimeOrchestrator
    discovery_engine: UnknownStreamDiscoveryEngine
    discovery_service: SemanticDiscoveryService
    processing_service: SemanticProcessingService
    review_runtime: SemanticReviewRuntime
    state_coordinator: SemanticStateCoordinator
    semantic_context_generation: SemanticContextGeneration
    persistence_service: SemanticPersistenceService

    def snapshot(self) -> SemanticApplicationSnapshot:
        """Capture every authoritative store at one coordinator generation."""
        self.processing_runtime.remove_stale_unknown_entries()
        with self.state_coordinator.lock:
            review = self.review_runtime.snapshot_review_state()
            return SemanticApplicationSnapshot(
                metadata=SemanticPersistenceMetadata(
                    schema_version=SEMANTIC_STATE_SCHEMA_VERSION,
                    model_fingerprint=self.persistence_service.model_fingerprint,
                    representation_contract_version=(
                        self.persistence_service.representation_contract_version
                    ),
                    policy_config={
                        "decision": {
                            "known_min_top1_votes": self.processing_runtime.decision_policy.config.known_min_top1_votes,
                            "known_min_mean_similarity": self.processing_runtime.decision_policy.config.known_min_mean_similarity,
                            "known_min_similarity_margin": self.processing_runtime.decision_policy.config.known_min_similarity_margin,
                            "unknown_max_mean_similarity": self.processing_runtime.decision_policy.config.unknown_max_mean_similarity,
                        },
                        "discovery": {
                            "min_cluster_size": self.discovery_engine.config.min_cluster_size,
                            "min_samples": self.discovery_engine.config.min_samples,
                            "cluster_selection_epsilon": self.discovery_engine.config.cluster_selection_epsilon,
                            "cluster_selection_method": self.discovery_engine.config.cluster_selection_method,
                            "allow_single_cluster": self.discovery_engine.config.allow_single_cluster,
                            "metric": self.discovery_engine.config.metric,
                        },
                    },
                ),
                generation=self.state_coordinator.generation,
                semantic_context_generation=(
                    self.semantic_context_generation.generation
                ),
                runtime_states=self.processing_runtime.state_store.snapshot(),
                unknown_pool=self.unknown_pool.snapshot(),
                trusted_evidence=self.evidence_store.snapshot(),
                constraints=self.constraint_store.snapshot(),
                confirmed_memberships=self.confirmed_membership_store.snapshot(),
                known_classes=self.known_class_registry.snapshot(),
                class_catalog=self.class_catalog.snapshot(),
                pending_candidates=review.pending_candidates,
                suppressed_candidates=review.suppressed_candidates,
            )

    def restore(self, snapshot: SemanticApplicationSnapshot) -> None:
        """Replace existing shared stores atomically, rolling all back on error."""
        self.persistence_service.serializer.validate(snapshot)
        previous = self.snapshot()
        review_snapshot_type = type(self.review_runtime.snapshot_review_state())
        try:
            with (
                self.state_coordinator.restore(snapshot.generation),
                self.semantic_context_generation.restore(
                    snapshot.semantic_context_generation
                ),
            ):
                self.processing_runtime.state_store.replace(snapshot.runtime_states)
                self.unknown_pool.replace(
                    snapshot.unknown_pool.entries, snapshot.unknown_pool.version
                )
                self.evidence_store.replace(snapshot.trusted_evidence)
                self.constraint_store.replace(snapshot.constraints)
                self.confirmed_membership_store.replace(snapshot.confirmed_memberships)
                self.known_class_registry.replace(snapshot.known_classes)
                self.class_catalog.replace(snapshot.class_catalog)
                self.review_runtime.replace_review_state(
                    review_snapshot_type(
                        snapshot.pending_candidates,
                        snapshot.suppressed_candidates,
                    )
                )
        except Exception:
            with (
                self.state_coordinator.restore(previous.generation),
                self.semantic_context_generation.restore(
                    previous.semantic_context_generation
                ),
            ):
                self.processing_runtime.state_store.replace(previous.runtime_states)
                self.unknown_pool.replace(
                    previous.unknown_pool.entries, previous.unknown_pool.version
                )
                self.evidence_store.replace(previous.trusted_evidence)
                self.constraint_store.replace(previous.constraints)
                self.confirmed_membership_store.replace(previous.confirmed_memberships)
                self.known_class_registry.replace(previous.known_classes)
                self.class_catalog.replace(previous.class_catalog)
                self.review_runtime.replace_review_state(
                    review_snapshot_type(
                        previous.pending_candidates,
                        previous.suppressed_candidates,
                    )
                )
            raise


def build_semantic_application(
    *,
    embedding_model: BaseEmbeddingModel,
    known_classes: Iterable[RepresentationClassCentroids],
    decision_policy: SemanticClassDecisionPolicy,
    state_store: SemanticRuntimeStateStore | None = None,
    unknown_pool: UnknownStreamPool | None = None,
    evidence_store: TrustedClassEvidenceStore | None = None,
    constraint_store: NegativeMembershipConstraintStore | None = None,
    confirmed_membership_store: ConfirmedSemanticMembershipStore | None = None,
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
    discovery_engine: UnknownStreamDiscoveryEngine | None = None,
    hdbscan_config: HDBSCANDiscoveryConfig | None = None,
    discovery_service: SemanticDiscoveryService | None = None,
    discovery_config: SemanticDiscoveryConfig | None = None,
    review_runtime: SemanticReviewRuntime | None = None,
    state_coordinator: SemanticStateCoordinator | None = None,
    semantic_context_generation: SemanticContextGeneration | None = None,
    persistence_repository: SemanticStateRepository | None = None,
    persistence_config: SemanticPersistenceConfig | None = None,
    persistence_serializer: SemanticSnapshotSerializer | None = None,
    model_fingerprint: str | None = None,
    embedding_model_identifier: str | None = None,
) -> SemanticApplication:
    """Build both runtimes around the exact same injected state objects."""
    inherited_coordinator = (
        getattr(review_runtime, "state_coordinator", None)
        if review_runtime is not None
        else (
            getattr(discovery_service.review_runtime, "state_coordinator", None)
            if discovery_service is not None
            else None
        )
    )
    coordinator = (
        state_coordinator or inherited_coordinator or SemanticStateCoordinator()
    )
    context_generation = semantic_context_generation or SemanticContextGeneration()
    injected_review_runtime = review_runtime or (
        discovery_service.review_runtime if discovery_service is not None else None
    )
    shared_unknown_pool = (
        unknown_pool
        if unknown_pool is not None
        else (
            injected_review_runtime.unknown_pool
            if injected_review_runtime is not None
            else UnknownStreamPool(coordinator)
        )
    )
    shared_evidence_store = (
        evidence_store
        if evidence_store is not None
        else (
            injected_review_runtime.evidence_store
            if injected_review_runtime is not None
            else TrustedClassEvidenceStore(coordinator)
        )
    )
    shared_constraint_store = (
        constraint_store
        if constraint_store is not None
        else (
            injected_review_runtime.constraint_store
            if injected_review_runtime is not None
            else NegativeMembershipConstraintStore(coordinator, context_generation)
        )
    )
    shared_confirmed_membership_store = (
        confirmed_membership_store
        if confirmed_membership_store is not None
        else (
            injected_review_runtime.confirmed_membership_store
            if injected_review_runtime is not None
            else ConfirmedSemanticMembershipStore(coordinator, context_generation)
        )
    )
    shared_feedback_workflow = (
        feedback_workflow
        if feedback_workflow is not None
        else (
            injected_review_runtime.workflow
            if injected_review_runtime is not None
            else SemanticFeedbackWorkflow()
        )
    )
    initial_known_classes = tuple(known_classes)
    shared_known_class_registry = (
        known_class_registry
        if known_class_registry is not None
        else (
            injected_review_runtime.known_class_registry
            if injected_review_runtime is not None
            and injected_review_runtime.known_class_registry is not None
            else KnownClassRegistry(
                coordinator=coordinator,
                context_generation=context_generation,
            )
        )
    )
    shared_constraint_store.set_context_generation(context_generation)
    shared_confirmed_membership_store.set_context_generation(context_generation)
    shared_known_class_registry.set_context_generation(context_generation)
    with coordinator.restore(coordinator.generation):
        for known_class in initial_known_classes:
            shared_known_class_registry.upsert(known_class)
    shared_class_catalog = (
        class_catalog
        if class_catalog is not None
        else (
            injected_review_runtime.class_catalog
            if injected_review_runtime is not None
            and injected_review_runtime.class_catalog is not None
            else SemanticClassCatalog(coordinator=coordinator)
        )
    )
    with coordinator.restore(coordinator.generation):
        for known_class in shared_known_class_registry.snapshot():
            shared_class_catalog.register(
                SemanticClassDefinition(known_class.class_id, known_class.class_name)
            )
    shared_feedback_lock = feedback_lock or (
        injected_review_runtime.feedback_lock
        if injected_review_runtime is not None
        else RLock()
    )

    processing_runtime = SemanticRuntimeOrchestrator(
        embedding_model=embedding_model,
        known_class_registry=shared_known_class_registry,
        decision_policy=decision_policy,
        state_store=(
            state_store
            if state_store is not None
            else SemanticRuntimeStateStore(coordinator)
        ),
        unknown_pool=shared_unknown_pool,
        constraint_store=shared_constraint_store,
        confirmed_membership_store=shared_confirmed_membership_store,
        semantic_context_generation=context_generation,
        feedback_lock=shared_feedback_lock,
        temporal_profiler=temporal_profiler,
        refresh_policy=refresh_policy,
        representation_builder=representation_builder,
        class_scorer=class_scorer,
        consensus_engine=consensus_engine,
        state_coordinator=coordinator,
    )
    shared_review_runtime = injected_review_runtime or SemanticReviewRuntime(
        unknown_pool=shared_unknown_pool,
        evidence_store=shared_evidence_store,
        constraint_store=shared_constraint_store,
        confirmed_membership_store=shared_confirmed_membership_store,
        processing_runtime=processing_runtime,
        workflow=shared_feedback_workflow,
        known_class_registry=shared_known_class_registry,
        class_catalog=shared_class_catalog,
        assembler=known_class_assembler,
        feedback_lock=shared_feedback_lock,
        state_coordinator=coordinator,
    )
    if shared_review_runtime.unknown_pool is not shared_unknown_pool:
        raise ValueError("review_runtime must reference the application UNKNOWN pool")
    if shared_review_runtime.evidence_store is not shared_evidence_store:
        raise ValueError("review_runtime must reference application evidence")
    if shared_review_runtime.constraint_store is not shared_constraint_store:
        raise ValueError("review_runtime must reference application constraints")
    if (
        shared_review_runtime.confirmed_membership_store
        is not shared_confirmed_membership_store
    ):
        raise ValueError("review_runtime must reference application memberships")
    if shared_review_runtime.workflow is not shared_feedback_workflow:
        raise ValueError("review_runtime must reference application workflow")
    if shared_review_runtime.known_class_registry is not shared_known_class_registry:
        raise ValueError("review_runtime must reference application registry")
    if shared_review_runtime.class_catalog is not shared_class_catalog:
        raise ValueError("review_runtime must reference application catalog")
    # An injected discovery/review service may come from another composition root.
    # Rebind it to this application's runtime while preserving its shared stores.
    shared_review_runtime.processing_runtime = processing_runtime
    shared_discovery_engine = discovery_engine or (
        discovery_service.discovery_engine
        if discovery_service is not None
        else UnknownStreamDiscoveryEngine(
            hdbscan_config or HDBSCANDiscoveryConfig(min_cluster_size=3)
        )
    )
    shared_discovery_service = discovery_service or SemanticDiscoveryService(
        shared_unknown_pool,
        shared_discovery_engine,
        shared_review_runtime,
        discovery_config,
    )
    if shared_discovery_service.unknown_pool is not shared_unknown_pool:
        raise ValueError(
            "discovery_service must reference the application UNKNOWN pool"
        )
    if shared_discovery_service.review_runtime is not shared_review_runtime:
        raise ValueError(
            "discovery_service must reference the application review runtime"
        )
    if shared_discovery_service.discovery_engine is not shared_discovery_engine:
        raise ValueError("discovery_service must reference the application engine")
    shared_review_runtime.set_discovery_requester(shared_discovery_service.request)
    shared_processing_service = processing_service or SemanticProcessingService(
        processing_runtime,
        config=processing_config,
        discovery_service=shared_discovery_service,
    )
    if shared_processing_service.runtime is not processing_runtime:
        raise ValueError("processing_service must reference the application runtime")
    if shared_processing_service.discovery_service is not shared_discovery_service:
        raise ValueError("processing_service must reference application discovery")
    for store in (
        shared_unknown_pool,
        shared_evidence_store,
        shared_constraint_store,
        shared_confirmed_membership_store,
        shared_known_class_registry,
        shared_class_catalog,
        processing_runtime.state_store,
    ):
        existing = getattr(store, "_coordinator", None)
        if existing not in (None, coordinator):
            raise ValueError(
                "Injected semantic store uses a different state coordinator"
            )
        store._coordinator = coordinator
    if getattr(shared_review_runtime, "state_coordinator", None) not in (
        None,
        coordinator,
    ):
        raise ValueError("review_runtime uses a different state coordinator")
    shared_review_runtime.state_coordinator = coordinator

    resolved_config = persistence_config or SemanticPersistenceConfig(enabled=False)
    if persistence_repository is None:
        if resolved_config.enabled:
            from services.database.postgres import postgres_client

            persistence_repository = PostgresSemanticStateRepository(postgres_client)
        else:
            persistence_repository = InMemorySemanticStateRepository()
    identifier = embedding_model_identifier or getattr(
        embedding_model, "model_name", type(embedding_model).__name__
    )
    fingerprint = model_fingerprint or create_model_fingerprint(str(identifier))
    holder: dict[str, SemanticApplication] = {}
    persistence_service = SemanticPersistenceService(
        repository=persistence_repository,
        coordinator=coordinator,
        snapshot_provider=lambda: holder["application"].snapshot(),
        restore_handler=lambda snapshot: holder["application"].restore(snapshot),
        model_fingerprint=fingerprint,
        representation_contract_version=SEMANTIC_REPRESENTATION_CONTRACT_VERSION,
        config=resolved_config,
        serializer=persistence_serializer,
    )
    application = SemanticApplication(
        unknown_pool=shared_unknown_pool,
        evidence_store=shared_evidence_store,
        constraint_store=shared_constraint_store,
        confirmed_membership_store=shared_confirmed_membership_store,
        feedback_workflow=shared_feedback_workflow,
        known_class_registry=shared_known_class_registry,
        class_catalog=shared_class_catalog,
        processing_runtime=processing_runtime,
        discovery_engine=shared_discovery_engine,
        discovery_service=shared_discovery_service,
        processing_service=shared_processing_service,
        review_runtime=shared_review_runtime,
        state_coordinator=coordinator,
        semantic_context_generation=context_generation,
        persistence_service=persistence_service,
    )
    holder["application"] = application
    return application
