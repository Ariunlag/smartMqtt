from pathlib import Path

from api import semantic_review as semantic_review_api
from fastapi.testclient import TestClient
from main import create_app
from services.embedding.base_model import BaseEmbeddingModel
from services.semantic import (
    CandidateIdentity,
    NegativeMembershipConstraint,
    NegativeMembershipConstraintStore,
    SemanticClassDecisionConfig,
    SemanticClassDecisionPolicy,
    SemanticFeedbackWorkflow,
    SemanticRuntimeStateStore,
    StreamProfiler,
    TrustedClassEvidenceStore,
    UnknownClusterCandidate,
    UnknownStreamPool,
    build_semantic_application,
)


class CountingEmbeddingModel(BaseEmbeddingModel):
    def __init__(self):
        self.calls = []

    def encode(self, texts):
        frozen = tuple(texts)
        self.calls.append(frozen)
        return [(1.0, 0.0) for _ in frozen]


def _policy():
    return SemanticClassDecisionPolicy(
        SemanticClassDecisionConfig(
            known_min_top1_votes=4,
            known_min_mean_similarity=0.8,
            known_min_similarity_margin=0.1,
            unknown_max_mean_similarity=0.2,
        )
    )


def _application(
    model=None,
    *,
    unknown_pool=None,
    evidence_store=None,
    constraint_store=None,
    workflow=None,
    state_store=None,
):
    return build_semantic_application(
        embedding_model=model or CountingEmbeddingModel(),
        known_classes=(),
        decision_policy=_policy(),
        unknown_pool=unknown_pool,
        evidence_store=evidence_store,
        constraint_store=constraint_store,
        feedback_workflow=workflow,
        state_store=state_store,
    )


def _profile(topic, value=1.0):
    return StreamProfiler().profile(topic, {}, {"reading": value})


def _prepare_candidate(application):
    for topic, value in (("A", 1.0), ("B", 2.0), ("C", 3.0)):
        application.processing_runtime.process(_profile(topic, value))
    application.review_runtime.register_candidate(
        UnknownClusterCandidate("key_value", 7, ("A", "B"))
    )


def _payload(**changes):
    payload = {
        "identity": {
            "representation_name": "key_value",
            "member_topics": ["A", "B"],
        },
        "class_id": "temperature",
        "semantic_class_name": "Temperature",
        "kept_topics": ["A"],
        "removed_topics": ["B"],
        "added_topics": ["C"],
    }
    payload.update(changes)
    return payload


def _client(application):
    return TestClient(
        create_app(semantic_application=application, manage_services=False)
    )


def test_application_owns_exact_shared_runtime_objects():
    unknown_pool = UnknownStreamPool()
    evidence_store = TrustedClassEvidenceStore()
    constraint_store = NegativeMembershipConstraintStore()
    workflow = SemanticFeedbackWorkflow()
    state_store = SemanticRuntimeStateStore()

    application = _application(
        unknown_pool=unknown_pool,
        evidence_store=evidence_store,
        constraint_store=constraint_store,
        workflow=workflow,
        state_store=state_store,
    )

    assert application.unknown_pool is unknown_pool
    assert application.evidence_store is evidence_store
    assert application.constraint_store is constraint_store
    assert (
        application.processing_runtime.confirmed_membership_store
        is application.confirmed_membership_store
    )
    assert application.feedback_workflow is workflow
    assert (
        application.processing_runtime.known_class_registry
        is application.known_class_registry
    )
    assert application.processing_runtime.constraint_store is constraint_store
    assert application.processing_runtime.unknown_pool is application.unknown_pool
    assert application.processing_runtime.state_store is state_store
    assert application.review_runtime.unknown_pool is application.unknown_pool
    assert application.review_runtime.evidence_store is application.evidence_store
    assert application.review_runtime.constraint_store is application.constraint_store
    assert (
        application.review_runtime.confirmed_membership_store
        is application.confirmed_membership_store
    )
    assert application.review_runtime.workflow is application.feedback_workflow
    assert (
        application.review_runtime.known_class_registry
        is application.known_class_registry
    )
    assert application.review_runtime.class_catalog is application.class_catalog


def test_unknown_processing_is_immediately_visible_to_review_without_copying():
    model = CountingEmbeddingModel()
    application = _application(model)

    result = application.processing_runtime.process(_profile("A"))

    assert result.decision.state.value == "UNKNOWN"
    assert application.review_runtime.list_unknown_topics() == ("A",)
    assert application.review_runtime.unknown_pool.get(
        "A"
    ) is application.unknown_pool.get("A")
    assert len(model.calls) == 1


def test_candidate_registration_reuses_the_shared_unknown_pool():
    application = _application()
    _prepare_candidate(application)
    pool_entries = application.unknown_pool.all()

    application.review_runtime.register_candidate(
        UnknownClusterCandidate("schema", 3, ("A", "C"))
    )

    assert application.unknown_pool.all() == pool_entries
    assert len(application.unknown_pool) == 3


def test_api_review_updates_shared_evidence_constraints_and_persists_across_requests():
    application = _application()
    _prepare_candidate(application)
    application.constraint_store.upsert(
        NegativeMembershipConstraint("A", "Temperature")
    )
    application.constraint_store.upsert(NegativeMembershipConstraint("A", "Humidity"))

    with _client(application) as client:
        candidates = client.get("/api/semantic-review/candidates")
        response = client.post("/api/semantic-review/reviews", json=_payload())
        constraints = client.get("/api/semantic-review/constraints")

    assert candidates.status_code == 200
    assert candidates.json()["available_unknown_topics"] == ["A", "B", "C"]
    assert response.status_code == 200
    assert response.json()["changed_representations"] == [
        "value_only",
        "key_only",
        "key_value",
        "schema",
        "numeric_key_only",
        "topic_key_value",
    ]
    assert len(application.evidence_store) == 6
    assert all(
        evidence.member_topics == ("A", "C")
        for evidence in application.evidence_store.all()
    )
    assert application.constraint_store.is_blocked("B", "Temperature")
    assert not application.constraint_store.is_blocked("A", "Temperature")
    assert application.constraint_store.is_blocked("A", "Humidity")
    assert tuple(
        membership.topic for membership in application.confirmed_membership_store.all()
    ) == ("A", "C")
    assert application.unknown_pool.get("A") is None
    assert application.unknown_pool.get("C") is None
    assert application.unknown_pool.get("B") is not None
    assert constraints.json()["constraints"] == [
        {"topic": "A", "semantic_class_name": "Humidity"},
        {"topic": "B", "semantic_class_name": "Temperature"},
    ]


def test_api_resolves_review_runtime_from_app_state_without_module_singleton():
    application = _application()
    application.review_runtime.register_candidate(
        UnknownClusterCandidate("key_only", 1, ("only/topic",))
    )

    with _client(application) as client:
        response = client.get("/api/semantic-review/candidates")

    assert response.json()["candidates"] == [
        {
            "representation_name": "key_only",
            "member_topics": ["only/topic"],
            "candidate_index": 1,
        }
    ]
    assert not hasattr(semantic_review_api, "_runtime")


def test_two_fastapi_apps_and_semantic_applications_remain_isolated():
    first = _application()
    second = _application()
    first.processing_runtime.process(_profile("first/topic"))
    second.processing_runtime.process(_profile("second/topic"))

    with _client(first) as first_client, _client(second) as second_client:
        first_response = first_client.get("/api/semantic-review/candidates").json()
        second_response = second_client.get("/api/semantic-review/candidates").json()

    assert first is not second
    assert first.unknown_pool is not second.unknown_pool
    assert first.evidence_store is not second.evidence_store
    assert first.constraint_store is not second.constraint_store
    assert first_response["available_unknown_topics"] == ["first/topic"]
    assert second_response["available_unknown_topics"] == ["second/topic"]


def test_application_factory_initializes_once_per_fastapi_instance():
    application = _application()
    calls = []
    app = create_app(
        semantic_application_factory=lambda: calls.append("build") or application,
        manage_services=False,
    )

    with TestClient(app) as client:
        assert client.get("/api/semantic-review/candidates").status_code == 200
    with TestClient(app) as client:
        assert client.get("/api/semantic-review/candidates").status_code == 200

    assert calls == ["build"]
    assert app.state.semantic_application is application


def test_failed_api_review_preserves_all_shared_state_and_pending_candidate():
    application = _application()
    _prepare_candidate(application)
    application.constraint_store.upsert(NegativeMembershipConstraint("old", "Other"))
    evidence_before = application.evidence_store.all()
    constraints_before = application.constraint_store.all()

    with _client(application) as client:
        response = client.post(
            "/api/semantic-review/reviews",
            json=_payload(added_topics=["missing"]),
        )

    assert response.status_code == 422
    assert application.evidence_store.all() == evidence_before
    assert application.constraint_store.all() == constraints_before
    assert application.review_runtime.list_candidates()[
        0
    ].identity == CandidateIdentity("key_value", ("A", "B"))


def test_runtime_no_refresh_behavior_and_review_api_contract_are_unchanged():
    model = CountingEmbeddingModel()
    application = _application(model)
    first = application.processing_runtime.process(_profile("topic", 1.0))
    second = application.processing_runtime.process(_profile("topic", 2.0))

    with _client(application) as client:
        missing = client.post("/api/semantic-review/reviews", json=_payload())

    assert first.refreshed is True
    assert second.refreshed is False
    assert second.embeddings is first.embeddings
    assert len(model.calls) == 1
    assert missing.status_code == 404
    assert "embedding" not in missing.text.lower()


def test_construction_is_lazy_with_respect_to_embedding_and_does_not_wire_mqtt():
    model = CountingEmbeddingModel()

    application = _application(model)

    assert model.calls == []
    assert application.processing_runtime.state_store.all() == ()
    module_source = Path("backend/services/semantic/semantic_application.py").read_text(
        encoding="utf-8"
    )
    assert "STEmbeddingModel" not in module_source
    assert "mqtt" not in module_source.lower()
