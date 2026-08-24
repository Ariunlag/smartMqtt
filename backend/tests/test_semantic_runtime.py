from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from threading import Lock

import pytest
from services.embedding.base_model import BaseEmbeddingModel
from services.semantic import (
    KnownClassRegistry,
    RepresentationClassCentroids,
    RepresentationEmbeddings,
    SemanticClassDecisionConfig,
    SemanticClassDecisionPolicy,
    SemanticClassDecisionState,
    SemanticRuntimeOrchestrator,
    SemanticRuntimeProcessingError,
    SemanticRuntimeStateStore,
    StreamProfiler,
    UnknownStreamPool,
)

VIEWS = tuple(RepresentationEmbeddings.__dataclass_fields__)


class ControlledEmbeddingModel(BaseEmbeddingModel):
    def __init__(self, vector=(1.0, 0.0)):
        self.vector = vector
        self.fail = False
        self.calls = []
        self._lock = Lock()

    def encode(self, texts):
        with self._lock:
            frozen_texts = tuple(texts)
            self.calls.append(frozen_texts)
            if self.fail:
                raise RuntimeError("model unavailable")
            vector = tuple(self.vector)
        return [vector for _ in frozen_texts]


class MutatingFailingUnknownPool(UnknownStreamPool):
    def __init__(self):
        super().__init__()
        self.fail_next_upsert = True

    def upsert(self, entry):
        super().upsert(entry)
        if self.fail_next_upsert:
            self.fail_next_upsert = False
            raise RuntimeError("pool write failed")


def _embeddings(vector):
    return RepresentationEmbeddings(**{name: vector for name in VIEWS})


def _known_class(class_id="known-a", class_name="Known A", vector=(1.0, 0.0)):
    return RepresentationClassCentroids(
        class_id=class_id,
        class_name=class_name,
        centroids=_embeddings(vector),
    )


def _policy():
    return SemanticClassDecisionPolicy(
        SemanticClassDecisionConfig(
            known_min_top1_votes=4,
            known_min_mean_similarity=0.8,
            known_min_similarity_margin=0.0,
            unknown_max_mean_similarity=0.2,
        )
    )


def _runtime(model=None, classes=None, state_store=None, unknown_pool=None):
    model = model or ControlledEmbeddingModel()
    return SemanticRuntimeOrchestrator(
        embedding_model=model,
        known_class_registry=KnownClassRegistry(
            (_known_class(),) if classes is None else classes
        ),
        decision_policy=_policy(),
        state_store=state_store,
        unknown_pool=unknown_pool,
    )


def _profile(topic="factory/sensor", tags=None, fields=None):
    return StreamProfiler().profile(topic, tags or {}, fields or {})


def test_first_observation_runs_complete_workflow_and_commits_state():
    model = ControlledEmbeddingModel()
    runtime = _runtime(model)

    result = runtime.process(_profile(fields={"temperature": 20.0}))

    assert result.refreshed is True
    assert result.refresh.should_refresh is True
    assert result.temporal_update.profile.observation_count == 1
    assert result.decision.state is SemanticClassDecisionState.KNOWN
    assert result.decision.candidate.class_id == "known-a"
    assert len(model.calls) == 1
    assert len(model.calls[0]) == 6
    assert runtime.state_store.get(result.topic).decision == result.decision
    assert runtime.unknown_pool.get(result.topic) is None


def test_numeric_variation_without_refresh_reuses_semantics_and_embedding():
    model = ControlledEmbeddingModel()
    runtime = _runtime(model)
    first = runtime.process(_profile(fields={"temperature": 20.0}))

    second = runtime.process(_profile(fields={"temperature": 21.5}))

    assert second.refreshed is False
    assert second.refresh.reasons == ()
    assert second.temporal_update.profile.observation_count == 2
    assert second.representations is first.representations
    assert second.embeddings is first.embeddings
    assert second.evidence == first.evidence
    assert second.consensus == first.consensus
    assert second.decision == first.decision
    assert second.evidence is not first.evidence
    assert len(model.calls) == 1


def test_metadata_and_schema_changes_refresh_and_embed_once_each():
    model = ControlledEmbeddingModel()
    runtime = _runtime(model)
    runtime.process(_profile(tags={"site": "A"}, fields={"reading": 1.0}))

    metadata = runtime.process(
        _profile(tags={"site": "A", "vendor": "Acme"}, fields={"reading": 1.0})
    )
    schema = runtime.process(
        _profile(
            tags={"site": "A", "vendor": "Acme"},
            fields={"reading": "one"},
        )
    )

    assert metadata.refreshed is True
    assert schema.refreshed is True
    assert len(model.calls) == 3


def test_known_decision_removes_a_stale_unknown_entry():
    model = ControlledEmbeddingModel(vector=(-1.0, 0.0))
    runtime = _runtime(model)
    first = runtime.process(_profile(fields={"reading": 1.0}))
    assert first.decision.state is SemanticClassDecisionState.UNKNOWN
    assert runtime.unknown_pool.get(first.topic) is not None

    model.vector = (1.0, 0.0)
    known = runtime.process(_profile(fields={"reading": 1.0, "quality": 1.0}))

    assert known.decision.state is SemanticClassDecisionState.KNOWN
    assert runtime.unknown_pool.get(known.topic) is None


def test_uncertain_decision_removes_a_stale_unknown_entry():
    model = ControlledEmbeddingModel(vector=(-1.0, 0.0))
    runtime = _runtime(model)
    unknown = runtime.process(_profile(fields={"reading": 1.0}))
    assert runtime.unknown_pool.get(unknown.topic) is not None

    model.vector = (0.6, 0.8)
    uncertain = runtime.process(_profile(fields={"reading": 1.0, "quality": 1.0}))

    assert uncertain.decision.state is SemanticClassDecisionState.UNCERTAIN
    assert runtime.unknown_pool.get(uncertain.topic) is None


def test_unknown_decision_upserts_once_and_repeated_no_refresh_is_idempotent():
    model = ControlledEmbeddingModel()
    runtime = _runtime(model, classes=())

    first = runtime.process(_profile(fields={"reading": 1.0}))
    second = runtime.process(_profile(fields={"reading": 2.0}))

    entry = runtime.unknown_pool.get(first.topic)
    assert first.decision.state is SemanticClassDecisionState.UNKNOWN
    assert second.refreshed is False
    assert entry.embeddings == first.embeddings
    assert entry.decision == first.decision
    assert len(runtime.unknown_pool) == 1
    assert len(model.calls) == 1


def test_transition_from_known_to_unknown_inserts_latest_embeddings():
    model = ControlledEmbeddingModel(vector=(1.0, 0.0))
    runtime = _runtime(model)
    known = runtime.process(_profile(fields={"reading": 1.0}))
    assert known.decision.state is SemanticClassDecisionState.KNOWN

    model.vector = (-1.0, 0.0)
    unknown = runtime.process(_profile(fields={"reading": 1.0, "quality": 1.0}))

    entry = runtime.unknown_pool.get(unknown.topic)
    assert unknown.decision.state is SemanticClassDecisionState.UNKNOWN
    assert entry.embeddings is unknown.embeddings
    assert entry.decision is unknown.decision


def test_embedding_failure_is_contextual_and_preserves_prior_state():
    model = ControlledEmbeddingModel(vector=(1.0, 0.0))
    runtime = _runtime(model)
    first = runtime.process(_profile(fields={"reading": 1.0}))
    state_before = runtime.state_store.get(first.topic)
    pool_before = runtime.unknown_pool.all()
    model.fail = True

    with pytest.raises(
        SemanticRuntimeProcessingError,
        match="factory/sensor.*representation embedding.*model unavailable",
    ) as captured:
        runtime.process(_profile(fields={"reading": 1.0, "quality": 1.0}))

    assert captured.value.stage == "representation embedding"
    assert runtime.state_store.get(first.topic) is state_before
    assert runtime.unknown_pool.all() == pool_before


def test_commit_failure_rolls_back_both_runtime_stores():
    pool = MutatingFailingUnknownPool()
    runtime = _runtime(ControlledEmbeddingModel(), classes=(), unknown_pool=pool)

    with pytest.raises(SemanticRuntimeProcessingError, match="state commit"):
        runtime.process(_profile(fields={"reading": 1.0}))

    assert runtime.state_store.get("factory/sensor") is None
    assert runtime.unknown_pool.get("factory/sensor") is None


def test_multiple_topics_keep_independent_temporal_state():
    model = ControlledEmbeddingModel()
    runtime = _runtime(model)

    second = runtime.process(_profile("z/topic", fields={"reading": 1.0}))
    first = runtime.process(_profile("a/topic", fields={"reading": 2.0}))
    updated = runtime.process(_profile("z/topic", fields={"reading": 3.0}))

    assert first.temporal_update.profile.observation_count == 1
    assert second.temporal_update.profile.observation_count == 1
    assert updated.temporal_update.profile.observation_count == 2
    assert tuple(
        state.temporal_profile.topic for state in runtime.state_store.all()
    ) == (
        "a/topic",
        "z/topic",
    )
    assert len(model.calls) == 2


def test_concurrent_same_topic_processing_is_serialized_without_duplicate_refresh():
    model = ControlledEmbeddingModel()
    runtime = _runtime(model)
    observation = _profile(fields={"reading": 1.0})

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = tuple(executor.map(runtime.process, (observation,) * 20))

    counts = sorted(
        result.temporal_update.profile.observation_count for result in results
    )
    assert counts == list(range(1, 21))
    assert (
        runtime.state_store.get(observation.topic).temporal_profile.observation_count
        == 20
    )
    assert sum(result.refreshed for result in results) == 1
    assert len(model.calls) == 1


def test_injected_stores_and_runtime_instances_are_isolated():
    first_store = SemanticRuntimeStateStore()
    first_pool = UnknownStreamPool()
    first = _runtime(
        ControlledEmbeddingModel(),
        classes=(),
        state_store=first_store,
        unknown_pool=first_pool,
    )
    second = _runtime(ControlledEmbeddingModel(), classes=())

    first.process(_profile(fields={"reading": 1.0}))

    assert first.state_store is first_store
    assert first.unknown_pool is first_pool
    assert len(first.state_store) == 1
    assert len(first.unknown_pool) == 1
    assert len(second.state_store) == 0
    assert len(second.unknown_pool) == 0


def test_process_result_and_topic_state_are_immutable():
    runtime = _runtime()
    result = runtime.process(_profile(fields={"reading": 1.0}))
    state = runtime.state_store.get(result.topic)

    with pytest.raises(FrozenInstanceError):
        result.refreshed = False
    with pytest.raises(FrozenInstanceError):
        state.decision = None


def test_known_class_registry_is_explicit_immutable_and_deterministic():
    model = ControlledEmbeddingModel()
    runtime = _runtime(
        model,
        classes=(
            _known_class("z-class", "Z class"),
            _known_class("a-class", "A class"),
        ),
    )

    result = runtime.process(_profile(fields={"reading": 1.0}))

    assert tuple(item.class_id for item in runtime.known_classes) == (
        "a-class",
        "z-class",
    )
    assert tuple(row.class_id for row in result.evidence.rows) == (
        "a-class",
        "z-class",
    )
