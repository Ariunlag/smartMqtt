"""Deterministic in-memory orchestration of the semantic runtime workflow."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from threading import Lock

from services.embedding.base_model import BaseEmbeddingModel

from .multi_view_consensus import MultiViewConsensusEngine, MultiViewConsensusResult
from .representation_class_scoring import (
    RepresentationClassCentroids,
    RepresentationClassEvidenceMatrix,
    RepresentationClassScorer,
)
from .representation_embedder import RepresentationEmbedder, RepresentationEmbeddings
from .representations import StreamRepresentations
from .semantic_class_decision import (
    SemanticClassDecision,
    SemanticClassDecisionPolicy,
    SemanticClassDecisionState,
)
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


class SemanticRuntimeStateStore:
    """Injectable in-memory latest-state store keyed by stream topic."""

    def __init__(self) -> None:
        self._states: dict[str, SemanticRuntimeTopicState] = {}

    def get(self, topic: str) -> SemanticRuntimeTopicState | None:
        return self._states.get(topic)

    def upsert(self, topic: str, state: SemanticRuntimeTopicState) -> None:
        if topic != state.temporal_profile.topic:
            raise ValueError("Runtime state topic does not match its store key")
        self._states[topic] = state

    def remove(self, topic: str) -> SemanticRuntimeTopicState | None:
        return self._states.pop(topic, None)

    def all(self) -> tuple[SemanticRuntimeTopicState, ...]:
        return tuple(self._states[topic] for topic in sorted(self._states))

    def __len__(self) -> int:
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
        known_classes: Iterable[RepresentationClassCentroids],
        decision_policy: SemanticClassDecisionPolicy,
        state_store: SemanticRuntimeStateStore | None = None,
        unknown_pool: UnknownStreamPool | None = None,
        temporal_profiler: TemporalStreamProfiler | None = None,
        refresh_policy: SemanticRefreshPolicy | None = None,
        representation_builder: StabilityAwareRepresentationBuilder | None = None,
        class_scorer: RepresentationClassScorer | None = None,
        consensus_engine: MultiViewConsensusEngine | None = None,
    ) -> None:
        self.known_classes = self._known_class_registry(known_classes)
        self.decision_policy = decision_policy
        self.state_store = (
            state_store if state_store is not None else SemanticRuntimeStateStore()
        )
        self.unknown_pool = (
            unknown_pool if unknown_pool is not None else UnknownStreamPool()
        )
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
                stage = "known-class scoring"
                evidence = self.class_scorer.score(embeddings, self.known_classes)
                stage = "multi-view consensus"
                consensus = self.consensus_engine.build(evidence)
                stage = "semantic class decision"
                decision = self.decision_policy.decide(consensus)
            else:
                if previous is None:
                    raise RuntimeError(
                        "Refresh policy skipped the first observation without cached semantics"
                    )
                representations = previous.representations
                embeddings = previous.embeddings
                evidence = previous.evidence
                consensus = previous.consensus
                decision = previous.decision
        except Exception as exc:
            if isinstance(exc, SemanticRuntimeProcessingError):
                raise
            raise SemanticRuntimeProcessingError(topic, stage, exc) from exc

        next_state = SemanticRuntimeTopicState(
            temporal_profile=temporal_update.profile,
            representations=representations,
            embeddings=embeddings,
            evidence=evidence,
            consensus=consensus,
            decision=decision,
        )
        self._commit(topic, previous, next_state)
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

    def _commit(
        self,
        topic: str,
        previous_state: SemanticRuntimeTopicState | None,
        next_state: SemanticRuntimeTopicState,
    ) -> None:
        previous_unknown = self.unknown_pool.get(topic)
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
            self._restore_unknown(topic, previous_unknown)
            raise SemanticRuntimeProcessingError(topic, "state commit", exc) from exc

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

    @staticmethod
    def _known_class_registry(
        classes: Iterable[RepresentationClassCentroids],
    ) -> tuple[RepresentationClassCentroids, ...]:
        registry = tuple(sorted(classes, key=lambda item: item.class_id))
        seen: set[str] = set()
        for known_class in registry:
            if known_class.class_id in seen:
                raise ValueError(f"Duplicate class_id: '{known_class.class_id}'")
            seen.add(known_class.class_id)
        return registry
