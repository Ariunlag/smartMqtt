"""Regression coverage for authoritative human semantic feedback."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Event, Lock

from fastapi.testclient import TestClient
from main import create_app
from services.embedding.base_model import BaseEmbeddingModel
from services.semantic import (
    CandidateConfirmationSource,
    CandidateIdentity,
    CandidateMembershipReview,
    NegativeMembershipConstraint,
    RepresentationClassCentroids,
    RepresentationClassScorer,
    RepresentationDiscoveryResult,
    RepresentationEmbeddings,
    SemanticClassDecisionConfig,
    SemanticClassDecisionPolicy,
    SemanticClassDecisionReason,
    SemanticClassDecisionState,
    SemanticClassDefinition,
    SemanticSnapshotSerializer,
    StreamProfiler,
    UnknownClusterCandidate,
    UnknownStreamDiscoveryResult,
    build_semantic_application,
)

VIEWS = tuple(RepresentationEmbeddings.__dataclass_fields__)


class CountingModel(BaseEmbeddingModel):
    def __init__(self) -> None:
        self.calls = 0

    def encode(self, texts):
        self.calls += 1
        return [(1.0, 0.0) for _ in texts]


def _known(class_id: str, class_name: str) -> RepresentationClassCentroids:
    return RepresentationClassCentroids(
        class_id,
        class_name,
        RepresentationEmbeddings(**{name: (1.0, 0.0) for name in VIEWS}),
    )


def _application(model=None):
    return build_semantic_application(
        embedding_model=model or CountingModel(),
        known_classes=(),
        decision_policy=SemanticClassDecisionPolicy(
            SemanticClassDecisionConfig(1, 0.8, 0.0, 0.2)
        ),
    )


def _profile(topic: str, value: float = 1.0):
    return StreamProfiler().profile(topic, {}, {"reading": value})


def _review(
    identity: CandidateIdentity,
    *,
    kept: tuple[str, ...],
    removed: tuple[str, ...] = (),
    added: tuple[str, ...] = (),
) -> CandidateMembershipReview:
    return CandidateMembershipReview(
        identity=identity,
        semantic_class_name="Temperature",
        kept_topics=kept,
        removed_topics=removed,
        added_topics=added,
        source=CandidateConfirmationSource.HUMAN,
    )


def _prepare(application, *topics: str) -> None:
    for index, topic in enumerate(topics, start=1):
        application.processing_runtime.process(_profile(topic, float(index)))


def _apply_initial_review(application):
    primary = UnknownClusterCandidate("key_value", 1, ("A", "B", "C"))
    overlapping = UnknownClusterCandidate("schema", 2, ("A", "D"))
    retained = UnknownClusterCandidate("schema", 3, ("C",))
    for candidate in (primary, overlapping, retained):
        application.review_runtime.register_candidate(candidate)
    result = application.review_runtime.apply_review(
        _review(
            CandidateIdentity.from_candidate(primary),
            kept=("A", "B"),
            removed=("C",),
            added=("D",),
        ),
        "temperature",
    )
    return result, primary, overlapping, retained


def test_review_reconciles_membership_unknown_pool_constraints_and_candidates():
    application = _application()
    _prepare(application, "A", "B", "C", "D")
    discovery_requests = []
    application.review_runtime.set_discovery_requester(
        lambda: discovery_requests.append("requested") or True
    )

    result, primary, overlapping, retained = _apply_initial_review(application)

    assert result.registry_updated
    assert tuple(
        (item.topic, item.class_id)
        for item in application.confirmed_membership_store.all()
    ) == (("A", "temperature"), ("B", "temperature"), ("D", "temperature"))
    assert application.constraint_store.is_blocked("C", "Temperature")
    assert not application.constraint_store.is_blocked("A", "Temperature")
    assert tuple(entry.topic for entry in application.unknown_pool.all()) == ("C",)
    pending = tuple(
        candidate.identity for candidate in application.review_runtime.list_candidates()
    )
    assert CandidateIdentity.from_candidate(primary) not in pending
    assert CandidateIdentity.from_candidate(overlapping) not in pending
    assert pending == (CandidateIdentity.from_candidate(retained),)
    assert discovery_requests == ["requested"]

    application.review_runtime.replace_discovery(
        UnknownStreamDiscoveryResult(
            tuple(RepresentationDiscoveryResult(name, (), ("C",)) for name in VIEWS)
        )
    )
    assert tuple(
        candidate.identity for candidate in application.review_runtime.list_candidates()
    ) == (CandidateIdentity.from_candidate(retained),)


def test_unrelated_pending_candidate_survives_review_and_later_discovery():
    application = _application()
    _prepare(application, "A", "B", "C", "D", "E", "F")
    unrelated = UnknownClusterCandidate("key_only", 9, ("E", "F"))
    application.review_runtime.register_candidate(unrelated)

    _apply_initial_review(application)
    application.review_runtime.replace_discovery(
        UnknownStreamDiscoveryResult(
            tuple(RepresentationDiscoveryResult(name, (), ()) for name in VIEWS)
        )
    )

    pending = tuple(
        candidate.identity for candidate in application.review_runtime.list_candidates()
    )
    assert CandidateIdentity.from_candidate(unrelated) in pending
    assert application.unknown_pool.get("E") is None
    assert application.unknown_pool.get("F") is None

    serializer = SemanticSnapshotSerializer()
    record = serializer.serialize(application.snapshot())
    restored = _application()
    restored.restore(
        serializer.deserialize(
            record,
            expected_model_fingerprint=(
                application.persistence_service.model_fingerprint
            ),
        )
    )
    retained = next(
        candidate
        for candidate in restored.review_runtime.list_candidates()
        if candidate.identity == CandidateIdentity.from_candidate(unrelated)
    )
    assert retained.retained_after_review

    restored.review_runtime.replace_discovery(
        UnknownStreamDiscoveryResult(
            tuple(
                RepresentationDiscoveryResult(
                    name,
                    (unrelated,) if name == unrelated.representation_name else (),
                    (),
                )
                for name in VIEWS
            )
        )
    )
    rediscovered = next(
        candidate
        for candidate in restored.review_runtime.list_candidates()
        if candidate.identity == CandidateIdentity.from_candidate(unrelated)
    )
    assert rediscovered.retained_after_review
    restored.review_runtime.replace_discovery(
        UnknownStreamDiscoveryResult(
            tuple(RepresentationDiscoveryResult(name, (), ()) for name in VIEWS)
        )
    )
    assert CandidateIdentity.from_candidate(unrelated) in tuple(
        candidate.identity for candidate in restored.review_runtime.list_candidates()
    )
    restored.review_runtime.clear_candidates()
    assert CandidateIdentity.from_candidate(unrelated) in tuple(
        candidate.identity for candidate in restored.review_runtime.list_candidates()
    )


def test_confirmed_topic_stays_known_without_reembedding_after_feedback():
    model = CountingModel()
    application = _application(model)
    _prepare(application, "A", "B", "C", "D")
    calls_before_review = model.calls
    _apply_initial_review(application)

    result = application.processing_runtime.process(_profile("A", 99.0))

    assert result.refreshed is False
    assert model.calls == calls_before_review
    assert result.decision.state is SemanticClassDecisionState.KNOWN
    assert result.decision.candidate is None
    assert result.decision.confirmed_class_id == "temperature"
    assert result.decision.confirmed_class_name == "Temperature"
    assert result.decision.class_id == "temperature"
    assert result.decision.class_name == "Temperature"
    assert result.decision.reasons == (
        SemanticClassDecisionReason.HUMAN_CONFIRMED_MEMBERSHIP,
    )
    assert application.unknown_pool.get("A") is None


def test_topic_state_api_exposes_human_class_identity_without_classifier_evidence():
    application = _application()
    _prepare(application, "A", "B", "C", "D")
    _apply_initial_review(application)

    with TestClient(
        create_app(semantic_application=application, manage_services=False)
    ) as client:
        response = client.get("/api/semantic-review/topic-states")

    assert response.status_code == 200
    topic = next(item for item in response.json()["topics"] if item["topic"] == "A")
    assert topic == {
        "topic": "A",
        "state": "KNOWN",
        "class_id": "temperature",
        "source": "HUMAN",
        "reasons": ["HUMAN_CONFIRMED_MEMBERSHIP"],
    }
    decision = application.processing_runtime.state_store.get("A").decision
    assert decision.candidate is None
    assert decision.runner_up is None
    assert decision.similarity_margin is None


def test_registry_change_lazily_invalidates_unrelated_topic_and_reuses_embeddings():
    model = CountingModel()
    application = _application(model)
    _prepare(application, "A", "B", "C", "D", "X")
    x_before = application.processing_runtime.state_store.get("X")
    calls_before_review = model.calls

    _apply_initial_review(application)

    x_stale = application.processing_runtime.state_store.get("X")
    assert x_stale is x_before
    assert not application.processing_runtime.is_state_current(x_stale)
    assert application.unknown_pool.get("X") is None
    assert model.calls == calls_before_review

    x_current = application.processing_runtime.get_current_state("X")

    assert x_current is not x_stale
    assert x_current.representations is x_stale.representations
    assert x_current.embeddings is x_stale.embeddings
    assert application.processing_runtime.is_state_current(x_current)
    assert x_current.decision.class_id == "temperature"
    assert model.calls == calls_before_review


def test_stale_context_survives_snapshot_restore_without_reembedding():
    model = CountingModel()
    application = _application(model)
    _prepare(application, "A", "B", "C", "D", "X")
    _apply_initial_review(application)
    stale = application.processing_runtime.state_store.get("X")
    calls_before = model.calls

    serializer = SemanticSnapshotSerializer()
    record = serializer.serialize(application.snapshot())
    persisted = serializer.deserialize(
        record,
        expected_model_fingerprint=application.persistence_service.model_fingerprint,
    )
    restored = _application(model)
    restored.restore(persisted)
    restored_stale = restored.processing_runtime.state_store.get("X")

    assert restored_stale == stale
    assert not restored.processing_runtime.is_state_current(restored_stale)
    current = restored.processing_runtime.get_current_state("X")
    assert current.embeddings is restored_stale.embeddings
    assert restored.processing_runtime.is_state_current(current)
    assert model.calls == calls_before


def test_schema_two_restore_recovers_human_identity_and_marks_context_stale():
    application = _application()
    _prepare(application, "A", "B", "C", "D")
    _apply_initial_review(application)
    serializer = SemanticSnapshotSerializer()
    current = serializer.serialize(application.snapshot())
    payload = dict(current.payload)
    payload.pop("semantic_context_generation")
    legacy_states = []
    for state in payload["runtime_states"]:
        state = dict(state)
        state.pop("semantic_context_generation")
        decision = dict(state["decision"])
        decision.pop("confirmed_class_id")
        decision.pop("confirmed_class_name")
        state["decision"] = decision
        legacy_states.append(state)
    payload["runtime_states"] = legacy_states

    restored = serializer.deserialize(
        replace(current, schema_version=2, payload=payload),
        expected_model_fingerprint=application.persistence_service.model_fingerprint,
    )

    state_a = next(
        state
        for state in restored.runtime_states
        if state.temporal_profile.topic == "A"
    )
    assert state_a.decision.class_id == "temperature"
    assert state_a.decision.class_name == "Temperature"
    assert state_a.decision.candidate is None
    assert state_a.semantic_context_generation == 0
    assert restored.semantic_context_generation == 1


class BlockingOnceScorer:
    def __init__(self) -> None:
        self._delegate = RepresentationClassScorer()
        self._armed = False
        self._guard = Lock()
        self.entered = Event()
        self.release = Event()

    def arm(self) -> None:
        with self._guard:
            self._armed = True

    def score(self, embeddings, classes):
        with self._guard:
            block = self._armed
            self._armed = False
        if block:
            self.entered.set()
            if not self.release.wait(timeout=5):
                raise TimeoutError("test did not release semantic scoring")
        return self._delegate.score(embeddings, classes)


def test_concurrent_mqtt_commit_cannot_overwrite_human_review():
    model = CountingModel()
    scorer = BlockingOnceScorer()
    application = build_semantic_application(
        embedding_model=model,
        known_classes=(),
        decision_policy=SemanticClassDecisionPolicy(
            SemanticClassDecisionConfig(1, 0.8, 0.0, 0.2)
        ),
        class_scorer=scorer,
    )
    _prepare(application, "A", "B", "C", "D")
    candidate = UnknownClusterCandidate("key_value", 1, ("A", "B", "C"))
    application.review_runtime.register_candidate(candidate)
    review = _review(
        CandidateIdentity.from_candidate(candidate),
        kept=("A", "B"),
        removed=("C",),
        added=("D",),
    )
    calls_before = model.calls
    review_started = Event()

    def apply_review():
        review_started.set()
        return application.review_runtime.apply_review(review, "temperature")

    scorer.arm()
    with ThreadPoolExecutor(max_workers=2) as executor:
        processing = executor.submit(
            application.processing_runtime.process,
            _profile("A", 99.0),
        )
        assert scorer.entered.wait(timeout=5)
        reviewing = executor.submit(apply_review)
        assert review_started.wait(timeout=5)
        scorer.release.set()
        processing.result(timeout=5)
        reviewing.result(timeout=5)

    membership = application.confirmed_membership_store.get("A")
    final_state = application.processing_runtime.get_current_state("A")
    assert membership is not None and membership.class_id == "temperature"
    assert final_state.decision.state is SemanticClassDecisionState.KNOWN
    assert final_state.decision.reasons == (
        SemanticClassDecisionReason.HUMAN_CONFIRMED_MEMBERSHIP,
    )
    assert final_state.decision.class_id == "temperature"
    assert final_state.decision.candidate is None
    assert application.unknown_pool.get("A") is None
    assert application.processing_runtime.is_state_current(final_state)
    assert model.calls == calls_before


def test_removed_topic_can_match_another_class_from_cached_embeddings():
    model = CountingModel()
    application = _application(model)
    _prepare(application, "A", "B", "C", "D")
    _apply_initial_review(application)
    calls_before = model.calls
    application.known_class_registry.upsert(_known("other", "Other"))
    application.class_catalog.register(SemanticClassDefinition("other", "Other"))

    result = application.processing_runtime.process(_profile("C", 100.0))

    assert result.refreshed is False
    assert model.calls == calls_before
    assert result.decision.state is SemanticClassDecisionState.KNOWN
    assert result.decision.candidate.class_id == "other"
    assert application.constraint_store.is_blocked("C", "Temperature")


def test_positive_correction_removes_matching_negative_constraint_atomically():
    application = _application()
    _prepare(application, "A", "B", "C", "D")
    _apply_initial_review(application)
    correction = UnknownClusterCandidate("schema", 4, ("C",))
    application.review_runtime.register_candidate(correction)

    application.review_runtime.apply_review(
        _review(CandidateIdentity.from_candidate(correction), kept=("C",)),
        "temperature",
    )

    membership = application.confirmed_membership_store.get("C")
    assert membership is not None and membership.class_id == "temperature"
    assert not application.constraint_store.is_blocked("C", "Temperature")
    assert application.unknown_pool.get("C") is None
    assert application.processing_runtime.state_store.get("C").decision.reasons == (
        SemanticClassDecisionReason.HUMAN_CONFIRMED_MEMBERSHIP,
    )


def test_late_review_failure_rolls_back_every_authoritative_store(monkeypatch):
    application = _application()
    _prepare(application, "A", "B", "C", "D")
    primary = UnknownClusterCandidate("key_value", 1, ("A", "B", "C"))
    application.review_runtime.register_candidate(primary)
    before = {
        "evidence": application.evidence_store.snapshot(),
        "constraints": application.constraint_store.snapshot(),
        "memberships": application.confirmed_membership_store.snapshot(),
        "catalog": application.class_catalog.snapshot(),
        "registry": application.known_class_registry.snapshot(),
        "unknown": application.unknown_pool.snapshot(),
        "review": application.review_runtime.snapshot_review_state(),
        "runtime": application.processing_runtime.state_store.snapshot(),
        "generation": application.state_coordinator.generation,
        "context_generation": application.semantic_context_generation.generation,
    }

    def fail_reconciliation(_topics=None, **_kwargs):
        raise RuntimeError("late reconciliation failure")

    monkeypatch.setattr(
        application.processing_runtime,
        "reconcile_context",
        fail_reconciliation,
    )

    try:
        application.review_runtime.apply_review(
            _review(
                CandidateIdentity.from_candidate(primary),
                kept=("A", "B"),
                removed=("C",),
                added=("D",),
            ),
            "temperature",
        )
    except RuntimeError as exc:
        assert str(exc) == "late reconciliation failure"
    else:
        raise AssertionError("review should fail")

    assert application.evidence_store.snapshot() == before["evidence"]
    assert application.constraint_store.snapshot() == before["constraints"]
    assert application.confirmed_membership_store.snapshot() == before["memberships"]
    assert application.class_catalog.snapshot() == before["catalog"]
    assert application.known_class_registry.snapshot() == before["registry"]
    assert application.unknown_pool.snapshot() == before["unknown"]
    assert application.review_runtime.snapshot_review_state() == before["review"]
    assert application.processing_runtime.state_store.snapshot() == before["runtime"]
    assert application.state_coordinator.generation == before["generation"]
    assert (
        application.semantic_context_generation.generation
        == before["context_generation"]
    )


def test_confirmed_membership_precedence_ignores_matching_negative_constraint():
    application = _application()
    _prepare(application, "A", "B", "C", "D")
    _apply_initial_review(application)
    application.constraint_store.upsert(
        NegativeMembershipConstraint("A", "Temperature")
    )

    result = application.processing_runtime.process(_profile("A", 5.0))

    assert result.decision.state is SemanticClassDecisionState.KNOWN
    assert result.decision.reasons == (
        SemanticClassDecisionReason.HUMAN_CONFIRMED_MEMBERSHIP,
    )
