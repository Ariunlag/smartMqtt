from api.semantic_review import get_semantic_review_runtime, router
from fastapi import FastAPI
from fastapi.testclient import TestClient
from services.semantic import (
    CandidateConfirmationSource,
    CandidateIdentity,
    NegativeMembershipConstraint,
    RepresentationEmbeddings,
    SemanticClassDecision,
    SemanticClassDecisionReason,
    SemanticClassDecisionState,
    SemanticFeedbackWorkflow,
    UnknownClusterCandidate,
    UnknownStreamEntry,
)
from services.semantic.semantic_review_runtime import SemanticReviewRuntime

VIEWS = tuple(RepresentationEmbeddings.__dataclass_fields__)


def _entry(topic: str, seed: float, invalid_view: str | None = None):
    vectors = {
        name: (() if name == invalid_view else (seed + index, seed + index + 0.5))
        for index, name in enumerate(VIEWS)
    }
    return UnknownStreamEntry(
        topic=topic,
        embeddings=RepresentationEmbeddings(**vectors),
        decision=SemanticClassDecision(
            SemanticClassDecisionState.UNKNOWN,
            None,
            None,
            None,
            (SemanticClassDecisionReason.NO_KNOWN_CLASSES,),
        ),
    )


def _candidate(*topics: str, representation: str = "key_value", index: int = 7):
    return UnknownClusterCandidate(representation, index, topics)


def _runtime(invalid_view: str | None = None):
    runtime = SemanticReviewRuntime()
    for topic, seed in (("C", 3.0), ("A", 1.0), ("B", 2.0)):
        runtime.register_unknown_entry(
            _entry(topic, seed, invalid_view if topic == "C" else None)
        )
    return runtime


def _client(runtime: SemanticReviewRuntime):
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_semantic_review_runtime] = lambda: runtime
    return TestClient(app)


def _payload(**changes):
    payload = {
        "identity": {
            "representation_name": "key_value",
            "member_topics": ["A", "B"],
        },
        "semantic_class_name": "Temperature",
        "kept_topics": ["A"],
        "removed_topics": ["B"],
        "added_topics": ["C"],
    }
    payload.update(changes)
    return payload


def test_empty_runtime_and_test_instances_are_isolated():
    first = SemanticReviewRuntime()
    second = SemanticReviewRuntime()
    first.register_candidate(_candidate("A", "B"))

    assert _client(first).get("/api/semantic-review/candidates").json()["candidates"]
    assert _client(second).get("/api/semantic-review/candidates").json() == {
        "candidates": [],
        "available_unknown_topics": [],
    }


def test_candidates_and_unknown_topics_are_deterministic_and_vector_free():
    runtime = _runtime()
    runtime.register_candidate(_candidate("B", "A", representation="schema", index=9))
    runtime.register_candidate(_candidate("C", "A", representation="key_only", index=2))

    response = _client(runtime).get("/api/semantic-review/candidates")

    assert response.status_code == 200
    assert response.json() == {
        "candidates": [
            {
                "representation_name": "key_only",
                "member_topics": ["A", "C"],
                "candidate_index": 2,
            },
            {
                "representation_name": "schema",
                "member_topics": ["A", "B"],
                "candidate_index": 9,
            },
        ],
        "available_unknown_topics": ["A", "B", "C"],
    }
    assert "embedding" not in response.text.lower()
    assert "centroid" not in response.text.lower()


def test_complete_review_updates_six_views_constraints_and_pending_candidate():
    runtime = _runtime()
    runtime.register_candidate(_candidate("A", "B"))

    response = _client(runtime).post("/api/semantic-review/reviews", json=_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["semantic_class_name"] == "Temperature"
    assert body["positive_topics"] == ["A", "C"]
    assert body["removed_topics"] == ["B"]
    assert body["changed_representations"] == list(VIEWS)
    assert len(body["prototypes"]) == 6
    assert all(item["member_topics"] == ["A", "C"] for item in body["prototypes"])
    assert all(item["member_count"] == 2 for item in body["prototypes"])
    assert "centroid" not in response.text.lower()
    assert runtime.list_candidates() == ()
    assert runtime.constraint_store.is_blocked("B", "Temperature")
    assert not runtime.constraint_store.is_blocked("A", "Temperature")
    assert not runtime.constraint_store.is_blocked("C", "Temperature")


def test_api_forces_human_feedback_source():
    class RecordingWorkflow(SemanticFeedbackWorkflow):
        source = None

        def apply_review(self, review, unknown_pool, evidence_store, constraint_store):
            self.source = review.source
            return super().apply_review(
                review, unknown_pool, evidence_store, constraint_store
            )

    workflow = RecordingWorkflow()
    runtime = _runtime()
    runtime.workflow = workflow
    runtime.register_candidate(_candidate("A", "B"))

    assert (
        _client(runtime)
        .post("/api/semantic-review/reviews", json=_payload(source="SYSTEM"))
        .status_code
        == 200
    )
    assert workflow.source is CandidateConfirmationSource.HUMAN


def test_positive_review_clears_only_matching_prior_constraint():
    runtime = _runtime()
    runtime.register_candidate(_candidate("A", "B"))
    runtime.constraint_store.upsert(NegativeMembershipConstraint("A", "Temperature"))
    runtime.constraint_store.upsert(NegativeMembershipConstraint("A", "Humidity"))

    response = _client(runtime).post("/api/semantic-review/reviews", json=_payload())

    assert response.status_code == 200
    assert response.json()["constraints_removed"] == [
        {"topic": "A", "semantic_class_name": "Temperature"}
    ]
    assert not runtime.constraint_store.is_blocked("A", "Temperature")
    assert runtime.constraint_store.is_blocked("A", "Humidity")


def test_unknown_candidate_returns_404():
    runtime = _runtime()

    response = _client(runtime).post("/api/semantic-review/reviews", json=_payload())

    assert response.status_code == 404


def test_invalid_partition_returns_422_and_keeps_candidate_and_state():
    runtime = _runtime()
    runtime.register_candidate(_candidate("A", "B"))
    before_constraints = runtime.constraint_store.all()
    before_evidence = runtime.evidence_store.all()

    response = _client(runtime).post(
        "/api/semantic-review/reviews",
        json=_payload(kept_topics=["A"], removed_topics=[]),
    )

    assert response.status_code == 422
    assert len(runtime.list_candidates()) == 1
    assert runtime.evidence_store.all() == before_evidence
    assert runtime.constraint_store.all() == before_constraints


def test_workflow_failure_is_atomic_and_keeps_candidate():
    runtime = _runtime(invalid_view="topic_key_value")
    runtime.register_candidate(_candidate("A", "B"))
    runtime.constraint_store.upsert(NegativeMembershipConstraint("old", "Other"))
    before_constraints = runtime.constraint_store.all()

    response = _client(runtime).post("/api/semantic-review/reviews", json=_payload())

    assert response.status_code == 422
    assert len(runtime.list_candidates()) == 1
    assert runtime.evidence_store.all() == ()
    assert runtime.constraint_store.all() == before_constraints


def test_constraints_endpoint_ordering_is_deterministic():
    runtime = SemanticReviewRuntime()
    runtime.constraint_store.upsert(NegativeMembershipConstraint("z", "Class A"))
    runtime.constraint_store.upsert(NegativeMembershipConstraint("a", "Class B"))
    runtime.constraint_store.upsert(NegativeMembershipConstraint("a", "Class A"))

    response = _client(runtime).get("/api/semantic-review/constraints")

    assert response.json()["constraints"] == [
        {"topic": "a", "semantic_class_name": "Class A"},
        {"topic": "z", "semantic_class_name": "Class A"},
        {"topic": "a", "semantic_class_name": "Class B"},
    ]


def test_identity_uses_canonical_topics_not_candidate_index():
    runtime = _runtime()
    runtime.register_candidate(_candidate("B", "A", index=99))

    response = _client(runtime).post("/api/semantic-review/reviews", json=_payload())

    assert response.status_code == 200
    assert CandidateIdentity("key_value", ("B", "A")).member_topics == ("A", "B")
