"""Regression coverage for authoritative human semantic feedback."""

from services.embedding.base_model import BaseEmbeddingModel
from services.semantic import (
    CandidateConfirmationSource,
    CandidateIdentity,
    CandidateMembershipReview,
    NegativeMembershipConstraint,
    RepresentationClassCentroids,
    RepresentationDiscoveryResult,
    RepresentationEmbeddings,
    SemanticClassDecisionConfig,
    SemanticClassDecisionPolicy,
    SemanticClassDecisionReason,
    SemanticClassDecisionState,
    SemanticClassDefinition,
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
    assert result.decision.reasons == (
        SemanticClassDecisionReason.HUMAN_CONFIRMED_MEMBERSHIP,
    )
    assert application.unknown_pool.get("A") is None


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
