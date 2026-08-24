"""Deterministic in-memory orchestration of the semantic runtime workflow."""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
from threading import Lock, RLock

from services.embedding.base_model import BaseEmbeddingModel

from .confirmed_membership import ConfirmedSemanticMembershipStore
from .known_class_registry import KnownClassRegistry
from .multi_view_consensus import MultiViewConsensusEngine, MultiViewConsensusResult
from .representation_class_scoring import (
    RepresentationClassEvidenceMatrix,
    RepresentationClassScorer,
)
from .representation_embedder import RepresentationEmbedder, RepresentationEmbeddings
from .representations import StreamRepresentations
from .semantic_class_decision import (
    SemanticClassDecision,
    SemanticClassDecisionPolicy,
    SemanticClassDecisionReason,
    SemanticClassDecisionState,
)
from .semantic_context import SemanticContextGeneration
from .semantic_feedback_workflow import NegativeMembershipConstraintStore
from .semantic_refresh import SemanticRefreshDecision, SemanticRefreshPolicy
from .stability_aware_representations import StabilityAwareRepresentationBuilder
from .stream_profiler import StreamProfile
from .temporal_profile import (
    TemporalProfileUpdate,
    TemporalStreamProfile,
    TemporalStreamProfiler,
)
from .unknown_stream_pool import UnknownStreamEntry, UnknownStreamPool


@dataclass(frozen=True, slots=True)
class SemanticRuntimeTopicState:
    """Latest temporal state and last successfully refreshed semantic artifacts."""

    temporal_profile: TemporalStreamProfile
    representations: StreamRepresentations
    embeddings: RepresentationEmbeddings
    evidence: RepresentationClassEvidenceMatrix
    consensus: MultiViewConsensusResult
    decision: SemanticClassDecision
    semantic_context_generation: int = 0

    def __post_init__(self) -> None:
        if (
            isinstance(self.semantic_context_generation, bool)
            or not isinstance(self.semantic_context_generation, int)
            or self.semantic_context_generation < 0
        ):
            raise ValueError("semantic_context_generation must be non-negative")


class SemanticRuntimeStateStore:
    """Injectable in-memory latest-state store keyed by stream topic."""

    def __init__(self, coordinator=None) -> None:
        self._states: dict[str, SemanticRuntimeTopicState] = {}
        self._lock = RLock()
        self._coordinator = coordinator

    def get(self, topic: str) -> SemanticRuntimeTopicState | None:
        with self._lock:
            return self._states.get(topic)

    def upsert(self, topic: str, state: SemanticRuntimeTopicState) -> None:
        if topic != state.temporal_profile.topic:
            raise ValueError("Runtime state topic does not match its store key")
        with self._lock:
            if self._states.get(topic) == state:
                return
            self._states[topic] = state
        if self._coordinator is not None:
            self._coordinator.mark_changed()

    def remove(self, topic: str) -> SemanticRuntimeTopicState | None:
        with self._lock:
            removed = self._states.pop(topic, None)
        if removed is not None and self._coordinator is not None:
            self._coordinator.mark_changed()
        return removed

    def all(self) -> tuple[SemanticRuntimeTopicState, ...]:
        with self._lock:
            return tuple(self._states[topic] for topic in sorted(self._states))

    def snapshot(self) -> tuple[SemanticRuntimeTopicState, ...]:
        return self.all()

    def replace(self, states: tuple[SemanticRuntimeTopicState, ...]) -> None:
        replacement = {state.temporal_profile.topic: state for state in states}
        if len(replacement) != len(states):
            raise ValueError("Runtime state snapshot contains duplicate topics")
        with self._lock:
            if self._states == replacement:
                return
            self._states = replacement
        if self._coordinator is not None:
            self._coordinator.mark_changed()

    def __len__(self) -> int:
        with self._lock:
            return len(self._states)


@dataclass(frozen=True, slots=True)
class SemanticRuntimeProcessResult:
    """Immutable outcome of one fully committed stream observation."""

    topic: str
    temporal_update: TemporalProfileUpdate
    refresh: SemanticRefreshDecision
    refreshed: bool
    representations: StreamRepresentations
    embeddings: RepresentationEmbeddings
    evidence: RepresentationClassEvidenceMatrix
    consensus: MultiViewConsensusResult
    decision: SemanticClassDecision


class SemanticRuntimeProcessingError(RuntimeError):
    """Contextual failure that identifies the topic and orchestration stage."""

    def __init__(self, topic: str, stage: str, cause: Exception) -> None:
        self.topic = topic
        self.stage = stage
        self.cause = cause
        super().__init__(
            f"Semantic runtime failed for topic '{topic}' during {stage}: {cause}"
        )


class SemanticRuntimeOrchestrator:
    """Compose existing semantic stages with per-topic atomic state handling."""

    def __init__(
        self,
        *,
        embedding_model: BaseEmbeddingModel,
        known_class_registry: KnownClassRegistry,
        decision_policy: SemanticClassDecisionPolicy,
        state_store: SemanticRuntimeStateStore | None = None,
        unknown_pool: UnknownStreamPool | None = None,
        constraint_store: NegativeMembershipConstraintStore | None = None,
        confirmed_membership_store: ConfirmedSemanticMembershipStore | None = None,
        semantic_context_generation: SemanticContextGeneration | None = None,
        feedback_lock=None,
        temporal_profiler: TemporalStreamProfiler | None = None,
        refresh_policy: SemanticRefreshPolicy | None = None,
        representation_builder: StabilityAwareRepresentationBuilder | None = None,
        class_scorer: RepresentationClassScorer | None = None,
        consensus_engine: MultiViewConsensusEngine | None = None,
        state_coordinator=None,
    ) -> None:
        self.known_class_registry = known_class_registry
        self.decision_policy = decision_policy
        self.state_store = (
            state_store if state_store is not None else SemanticRuntimeStateStore()
        )
        self.unknown_pool = (
            unknown_pool if unknown_pool is not None else UnknownStreamPool()
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
        self.semantic_context_generation = semantic_context_generation
        self.feedback_lock = feedback_lock or RLock()
        self.state_coordinator = state_coordinator
        self.temporal_profiler = temporal_profiler or TemporalStreamProfiler()
        self.refresh_policy = refresh_policy or SemanticRefreshPolicy()
        self.representation_builder = (
            representation_builder or StabilityAwareRepresentationBuilder()
        )
        self.embedder = RepresentationEmbedder(embedding_model)
        self.class_scorer = class_scorer or RepresentationClassScorer()
        self.consensus_engine = consensus_engine or MultiViewConsensusEngine()
        self._topic_locks: dict[str, Lock] = {}
        self._topic_locks_guard = Lock()

    def process(self, observation: StreamProfile) -> SemanticRuntimeProcessResult:
        """Process and atomically commit one immutable stream observation."""
        if not isinstance(observation, StreamProfile):
            raise TypeError("observation must be a StreamProfile")
        topic = observation.topic
        with self._lock_for(topic):
            return self._process_locked(observation)

    def _process_locked(
        self, observation: StreamProfile
    ) -> SemanticRuntimeProcessResult:
        topic = observation.topic
        previous = self.state_store.get(topic)

        stage = "temporal profiling"
        try:
            temporal_update = self.temporal_profiler.update(
                previous.temporal_profile if previous is not None else None,
                observation,
            )
            stage = "refresh evaluation"
            refresh = self.refresh_policy.evaluate(temporal_update)

            if refresh.should_refresh:
                stage = "representation building"
                representations = self.representation_builder.build(
                    temporal_update.profile
                )
                stage = "representation embedding"
                embeddings = self.embedder.embed(representations)
            else:
                if previous is None:
                    raise RuntimeError(
                        "Refresh policy skipped the first observation without cached semantics"
                    )
                representations = previous.representations
                embeddings = previous.embeddings
        except Exception as exc:
            if isinstance(exc, SemanticRuntimeProcessingError):
                raise
            raise SemanticRuntimeProcessingError(topic, stage, exc) from exc

        transaction = (
            self.state_coordinator.transaction()
            if self.state_coordinator is not None
            else nullcontext()
        )
        try:
            with self.feedback_lock, transaction:
                stage = (
                    "semantic context evaluation"
                    if refresh.should_refresh
                    else "cached semantic context evaluation"
                )
                evidence, consensus, decision = self._evaluate_context(
                    topic, embeddings
                )
                next_state = SemanticRuntimeTopicState(
                    temporal_profile=temporal_update.profile,
                    representations=representations,
                    embeddings=embeddings,
                    evidence=evidence,
                    consensus=consensus,
                    decision=decision,
                    semantic_context_generation=self.current_context_generation,
                )
                self._commit(topic, previous, next_state)
        except Exception as exc:
            if isinstance(exc, SemanticRuntimeProcessingError):
                raise
            raise SemanticRuntimeProcessingError(topic, stage, exc) from exc
        return SemanticRuntimeProcessResult(
            topic=topic,
            temporal_update=temporal_update,
            refresh=refresh,
            refreshed=refresh.should_refresh,
            representations=representations,
            embeddings=embeddings,
            evidence=evidence,
            consensus=consensus,
            decision=decision,
        )

    def reconcile_context(
        self,
        topics: tuple[str, ...] | None = None,
        *,
        coordinated: bool = False,
    ) -> None:
        """Re-score cached embeddings after authoritative feedback changes."""
        selected = (
            tuple(sorted(set(topics)))
            if topics is not None
            else tuple(state.temporal_profile.topic for state in self.state_store.all())
        )
        for topic in selected:
            topic_lock = nullcontext() if coordinated else self._lock_for(topic)
            transaction = (
                nullcontext()
                if coordinated or self.state_coordinator is None
                else self.state_coordinator.transaction()
            )
            with topic_lock, self.feedback_lock, transaction:
                previous = self.state_store.get(topic)
                if previous is None:
                    continue
                try:
                    evidence, consensus, decision = self._evaluate_context(
                        topic, previous.embeddings
                    )
                    next_state = SemanticRuntimeTopicState(
                        temporal_profile=previous.temporal_profile,
                        representations=previous.representations,
                        embeddings=previous.embeddings,
                        evidence=evidence,
                        consensus=consensus,
                        decision=decision,
                        semantic_context_generation=self.current_context_generation,
                    )
                    self._commit(topic, previous, next_state)
                except Exception as exc:
                    if isinstance(exc, SemanticRuntimeProcessingError):
                        raise
                    raise SemanticRuntimeProcessingError(
                        topic, "cached semantic context reconciliation", exc
                    ) from exc

    @property
    def current_context_generation(self) -> int:
        if self.semantic_context_generation is None:
            return 0
        return self.semantic_context_generation.generation

    def is_state_current(self, state: SemanticRuntimeTopicState) -> bool:
        """Return whether cached scoring used the current class context."""
        return state.semantic_context_generation == self.current_context_generation

    def get_current_state(self, topic: str) -> SemanticRuntimeTopicState | None:
        """Lazily re-score one stale topic without rebuilding embeddings."""
        state = self.state_store.get(topic)
        if state is not None and not self.is_state_current(state):
            self.reconcile_context((topic,))
            state = self.state_store.get(topic)
        return state

    def current_states(self) -> tuple[SemanticRuntimeTopicState, ...]:
        """Return current vector-free decisions, lazily refreshing stale topics."""
        topics = tuple(state.temporal_profile.topic for state in self.state_store.all())
        return tuple(
            state
            for topic in topics
            if (state := self.get_current_state(topic)) is not None
        )

    def remove_stale_unknown_entries(self) -> tuple[str, ...]:
        """Exclude stale UNKNOWN evidence from discovery without re-scoring it."""
        removed: list[str] = []
        transaction = (
            self.state_coordinator.transaction()
            if self.state_coordinator is not None
            else nullcontext()
        )
        with self.feedback_lock, transaction:
            for entry in self.unknown_pool.all():
                state = self.state_store.get(entry.topic)
                if (
                    state is None or not self.is_state_current(state)
                ) and self.unknown_pool.remove(entry.topic) is not None:
                    removed.append(entry.topic)
        return tuple(removed)

    def _evaluate_context(
        self,
        topic: str,
        embeddings: RepresentationEmbeddings,
    ) -> tuple[
        RepresentationClassEvidenceMatrix,
        MultiViewConsensusResult,
        SemanticClassDecision,
    ]:
        with self.feedback_lock:
            known_classes = self.known_class_registry.snapshot()
            evidence = self.class_scorer.score(embeddings, known_classes)
            unfiltered_consensus = self.consensus_engine.build(evidence)
            eligible = self.constraint_store.filter_allowed(
                topic, unfiltered_consensus.classes
            )
            consensus = MultiViewConsensusResult(
                view_winners=unfiltered_consensus.view_winners,
                classes=eligible,
            )
            membership = self.confirmed_membership_store.get(topic)
            if membership is not None:
                registered = self.known_class_registry.get(membership.class_id)
                if (
                    registered is None
                    or registered.class_name != membership.semantic_class_name
                ):
                    raise ValueError(
                        "Human-confirmed membership references an unavailable class"
                    )
                decision = SemanticClassDecision(
                    state=SemanticClassDecisionState.KNOWN,
                    candidate=None,
                    runner_up=None,
                    similarity_margin=None,
                    reasons=(SemanticClassDecisionReason.HUMAN_CONFIRMED_MEMBERSHIP,),
                    confirmed_class_id=membership.class_id,
                    confirmed_class_name=membership.semantic_class_name,
                )
            elif unfiltered_consensus.classes and not eligible:
                decision = SemanticClassDecision(
                    state=SemanticClassDecisionState.UNKNOWN,
                    candidate=None,
                    runner_up=None,
                    similarity_margin=None,
                    reasons=(SemanticClassDecisionReason.ALL_CLASSES_BLOCKED,),
                )
            else:
                decision = self.decision_policy.decide(consensus)
            return evidence, consensus, decision

    def _commit(
        self,
        topic: str,
        previous_state: SemanticRuntimeTopicState | None,
        next_state: SemanticRuntimeTopicState,
    ) -> None:
        transaction = (
            self.state_coordinator.transaction()
            if self.state_coordinator is not None
            else self.feedback_lock
        )
        with transaction:
            previous_unknown_snapshot = self.unknown_pool.snapshot()
            try:
                self.state_store.upsert(topic, next_state)
                if next_state.decision.state is SemanticClassDecisionState.UNKNOWN:
                    self.unknown_pool.upsert(
                        UnknownStreamEntry(
                            topic=topic,
                            embeddings=next_state.embeddings,
                            decision=next_state.decision,
                        )
                    )
                else:
                    self.unknown_pool.remove(topic)
            except Exception as exc:
                self._restore_state(topic, previous_state)
                self.unknown_pool.replace(
                    previous_unknown_snapshot.entries,
                    previous_unknown_snapshot.version,
                )
                raise SemanticRuntimeProcessingError(
                    topic, "state commit", exc
                ) from exc

    def _restore_state(
        self, topic: str, previous: SemanticRuntimeTopicState | None
    ) -> None:
        if previous is None:
            self.state_store.remove(topic)
        else:
            self.state_store.upsert(topic, previous)

    def _restore_unknown(self, topic: str, previous: UnknownStreamEntry | None) -> None:
        if previous is None:
            self.unknown_pool.remove(topic)
        else:
            self.unknown_pool.upsert(previous)

    def _lock_for(self, topic: str) -> Lock:
        with self._topic_locks_guard:
            lock = self._topic_locks.get(topic)
            if lock is None:
                lock = Lock()
                self._topic_locks[topic] = lock
            return lock

    @property
    def known_classes(self):
        """Return the current immutable registry snapshot for diagnostics."""
        return self.known_class_registry.snapshot()
