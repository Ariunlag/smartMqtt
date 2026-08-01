from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError

import pytest
from fastapi.testclient import TestClient
from main import create_app
from services.embedding.base_model import BaseEmbeddingModel
from services.semantic import (
    CandidateConfirmationSource,
    CandidateIdentity,
    CandidateMembershipReview,
    KnownClassAssembler,
    KnownClassAssemblyResult,
    KnownClassRegistry,
    MultiViewConsensusEngine,
    NegativeMembershipConstraint,
    RepresentationClassCentroids,
    RepresentationEmbeddings,
    SemanticClassCatalog,
    SemanticClassDecisionConfig,
    SemanticClassDecisionPolicy,
    SemanticClassDecisionReason,
    SemanticClassDecisionState,
    SemanticClassDefinition,
    StreamProfiler,
    UnknownClusterCandidate,
    build_semantic_application,
)

VIEWS = tuple(RepresentationEmbeddings.__dataclass_fields__)


class MutableEmbeddingModel(BaseEmbeddingModel):
    def __init__(self, vector=(1.0, 0.0)):
        self.vector = vector
        self.calls = []

    def encode(self, texts):
        frozen = tuple(texts)
        self.calls.append(frozen)
        return [self.vector for _ in frozen]


class RecordingConsensusEngine:
    def __init__(self):
        self.last_unfiltered = None

    def build(self, evidence):
        self.last_unfiltered = MultiViewConsensusEngine.build(evidence)
        return self.last_unfiltered


class IncompleteAssembler(KnownClassAssembler):
    def assemble(self, request, evidence_store):
        return KnownClassAssemblyResult(
            class_id=request.class_id,
            semantic_class_name=request.semantic_class_name,
            missing_representations=("schema",),
            centroids=None,
        )


def _embeddings(vector=(1.0, 0.0), *, per_view=None):
    values = {name: vector for name in VIEWS}
    values.update(per_view or {})
    return RepresentationEmbeddings(**values)


def _known(class_id, class_name, vector=(1.0, 0.0), *, per_view=None):
    return RepresentationClassCentroids(
        class_id=class_id,
        class_name=class_name,
        centroids=_embeddings(vector, per_view=per_view),
    )


def _policy(votes=1, known=0.8, unknown=0.2):
    return SemanticClassDecisionPolicy(
        SemanticClassDecisionConfig(votes, known, 0.0, unknown)
    )


def _application(
    model=None,
    classes=(),
    *,
    policy=None,
    consensus_engine=None,
    assembler=None,
):
    return build_semantic_application(
        embedding_model=model or MutableEmbeddingModel(),
        known_classes=classes,
        decision_policy=policy or _policy(),
        consensus_engine=consensus_engine,
        known_class_assembler=assembler,
    )


def _profile(topic, fields=None):
    return StreamProfiler().profile(topic, {}, fields or {"reading": 1.0})


def _review(identity, class_name, kept, removed=(), added=()):
    return CandidateMembershipReview(
        identity=identity,
        semantic_class_name=class_name,
        kept_topics=kept,
        removed_topics=removed,
        added_topics=added,
        source=CandidateConfirmationSource.HUMAN,
    )


def _prepare_unknown(application, *topics):
    for index, topic in enumerate(topics, start=1):
        application.processing_runtime.process(
            _profile(topic, {"reading": float(index)})
        )


def _payload(class_id="temperature", class_name="Temperature"):
    return {
        "identity": {
            "representation_name": "key_value",
            "member_topics": ["A", "B"],
        },
        "class_id": class_id,
        "semantic_class_name": class_name,
        "kept_topics": ["A"],
        "removed_topics": ["B"],
        "added_topics": ["C"],
    }


def test_initial_classes_seed_registry_and_explicit_bijective_catalog():
    classes = (
        _known("z", "Zulu"),
        _known("a", "Alpha", (0.0, 1.0)),
    )

    application = _application(classes=classes)

    assert tuple(item.class_id for item in application.known_class_registry.all()) == (
        "a",
        "z",
    )
    assert application.class_catalog.snapshot() == (
        SemanticClassDefinition("a", "Alpha"),
        SemanticClassDefinition("z", "Zulu"),
    )
    assert (
        application.processing_runtime.known_class_registry
        is application.known_class_registry
    )
    assert (
        application.review_runtime.known_class_registry
        is application.known_class_registry
    )


def test_registry_snapshot_is_immutable_deterministic_and_latest_id_wins():
    registry = KnownClassRegistry()
    first = _known("b", "Beta", (0.0, 1.0))
    replacement = _known("b", "Beta", (1.0, 0.0))
    registry.upsert(first)
    registry.upsert(_known("a", "Alpha"))
    registry.upsert(replacement)

    snapshot = registry.snapshot()

    assert tuple(item.class_id for item in snapshot) == ("a", "b")
    assert registry.get("b") is replacement
    assert isinstance(snapshot, tuple)
    with pytest.raises(FrozenInstanceError):
        snapshot[0].class_name = "changed"


def test_catalog_rejects_id_or_name_conflicts_without_changing_mapping():
    catalog = SemanticClassCatalog((SemanticClassDefinition("a", "Alpha"),))

    with pytest.raises(ValueError, match="class_id 'a'"):
        catalog.register(SemanticClassDefinition("a", "Other"))
    with pytest.raises(ValueError, match="semantic_class_name 'Alpha'"):
        catalog.register(SemanticClassDefinition("other", "Alpha"))

    assert catalog.snapshot() == (SemanticClassDefinition("a", "Alpha"),)


def test_runtime_reads_new_registry_snapshot_only_on_refresh():
    model = MutableEmbeddingModel()
    application = _application(model=model, classes=(_known("a", "Alpha"),))
    first = application.processing_runtime.process(_profile("topic"))
    application.known_class_registry.upsert(_known("b", "Beta"))

    cached = application.processing_runtime.process(_profile("topic", {"reading": 2.0}))
    refreshed = application.processing_runtime.process(
        _profile("topic", {"reading": 2.0, "quality": 1.0})
    )

    assert tuple(row.class_id for row in first.evidence.rows) == ("a",)
    assert cached.refreshed is False
    assert cached.evidence is first.evidence
    assert tuple(row.class_id for row in refreshed.evidence.rows) == ("a", "b")
    assert len(model.calls) == 2


def test_blocked_top_candidate_is_filtered_without_modifying_evidence_or_consensus():
    split_a = {name: (0.0, 1.0) for name in VIEWS[-2:]}
    split_b = {name: (0.0, 1.0) for name in VIEWS[:4]}
    classes = (
        _known("a", "Alpha", per_view=split_a),
        _known("b", "Beta", per_view=split_b),
    )
    recorder = RecordingConsensusEngine()
    application = _application(
        classes=classes,
        policy=_policy(votes=2, known=0.3, unknown=-0.1),
        consensus_engine=recorder,
    )
    application.constraint_store.upsert(NegativeMembershipConstraint("topic", "Alpha"))

    result = application.processing_runtime.process(_profile("topic"))
    unfiltered = recorder.last_unfiltered

    assert tuple(item.class_name for item in unfiltered.classes) == ("Alpha", "Beta")
    assert tuple(item.class_name for item in result.consensus.classes) == ("Beta",)
    assert result.consensus.classes[0] is unfiltered.classes[1]
    assert result.consensus.view_winners is unfiltered.view_winners
    assert result.decision.state is SemanticClassDecisionState.KNOWN
    assert result.decision.candidate is result.consensus.classes[0]
    assert result.decision.candidate.class_name == "Beta"
    assert tuple(row.class_id for row in result.evidence.rows) == ("a", "b")
    assert result.consensus.classes[0].top1_votes == 2
    assert result.consensus.classes[0].mean_rank == unfiltered.classes[1].mean_rank
    assert (
        result.consensus.classes[0].mean_similarity
        == unfiltered.classes[1].mean_similarity
    )


def test_all_blocked_is_explicit_unknown_and_enters_unknown_pool():
    application = _application(classes=(_known("a", "Alpha"),))
    application.constraint_store.upsert(NegativeMembershipConstraint("topic", "Alpha"))

    result = application.processing_runtime.process(_profile("topic"))

    assert result.consensus.classes == ()
    assert result.consensus.top_candidate is None
    assert result.decision.state is SemanticClassDecisionState.UNKNOWN
    assert result.decision.candidate is None
    assert result.decision.reasons == (SemanticClassDecisionReason.ALL_CLASSES_BLOCKED,)
    assert application.unknown_pool.get("topic").decision is result.decision


def test_review_conflict_and_incomplete_assembly_roll_back_every_shared_store():
    application = _application(assembler=IncompleteAssembler())
    _prepare_unknown(application, "A", "B", "C")
    existing = _known("existing", "Existing")
    application.known_class_registry.upsert(existing)
    application.class_catalog.register(SemanticClassDefinition("existing", "Existing"))
    candidate = UnknownClusterCandidate("key_value", 1, ("A", "B"))
    application.review_runtime.register_candidate(candidate)
    review = _review(
        CandidateIdentity.from_candidate(candidate), "New", ("A",), ("B",), ("C",)
    )
    snapshots = (
        application.evidence_store.snapshot(),
        application.constraint_store.snapshot(),
        application.class_catalog.snapshot(),
        application.known_class_registry.snapshot(),
    )

    with pytest.raises(ValueError, match="incomplete known class"):
        application.review_runtime.apply_review(review, "new")

    assert application.evidence_store.snapshot() == snapshots[0]
    assert application.constraint_store.snapshot() == snapshots[1]
    assert application.class_catalog.snapshot() == snapshots[2]
    assert application.known_class_registry.snapshot() == snapshots[3]
    assert application.review_runtime.list_candidates()[0].identity == review.identity

    with pytest.raises(ValueError, match="class_id 'existing'"):
        application.review_runtime.apply_review(review, "existing")
    assert application.evidence_store.snapshot() == snapshots[0]
    assert application.constraint_store.snapshot() == snapshots[1]


def test_review_api_requires_class_id_and_lists_classes_without_vectors():
    application = _application(
        classes=(
            _known("z", "Zulu"),
            _known("a", "Alpha", (0.0, 1.0)),
        )
    )
    _prepare_unknown(application, "A", "B", "C")
    application.review_runtime.register_candidate(
        UnknownClusterCandidate("key_value", 1, ("A", "B"))
    )
    app = create_app(semantic_application=application, manage_services=False)
    payload = _payload()
    payload.pop("class_id")

    with TestClient(app) as client:
        invalid = client.post("/api/semantic-review/reviews", json=payload)
        classes = client.get("/api/semantic-review/classes")

    assert invalid.status_code == 422
    assert classes.json() == {
        "classes": [
            {"class_id": "a", "semantic_class_name": "Alpha"},
            {"class_id": "z", "semantic_class_name": "Zulu"},
        ]
    }
    assert "centroid" not in classes.text.lower()
    assert "embedding" not in classes.text.lower()


def test_concurrent_processing_observes_only_complete_registry_snapshots():
    application = _application(classes=(_known("a", "Alpha"),))

    def process(index):
        return tuple(
            row.class_id
            for row in application.processing_runtime.process(
                _profile(f"topic/{index}")
            ).evidence.rows
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(process, index) for index in range(20)]
        application.known_class_registry.upsert(_known("b", "Beta"))
        snapshots = tuple(future.result() for future in futures)

    assert set(snapshots) <= {("a",), ("a", "b")}
    assert application.known_class_registry.snapshot() == (
        application.known_class_registry.get("a"),
        application.known_class_registry.get("b"),
    )


def test_end_to_end_review_publishes_class_then_constraint_blocks_live_decision():
    model = MutableEmbeddingModel()
    application = _application(model=model)
    _prepare_unknown(application, "A", "B", "C")
    candidate = UnknownClusterCandidate("key_value", 1, ("A", "B"))
    application.review_runtime.register_candidate(candidate)
    app = create_app(semantic_application=application, manage_services=False)

    with TestClient(app) as client:
        response = client.post("/api/semantic-review/reviews", json=_payload())

    assert response.status_code == 200
    assert response.json()["class_id"] == "temperature"
    assert response.json()["registry_updated"] is True
    assert response.json()["changed_representations"] == list(VIEWS)
    published = application.known_class_registry.get("temperature")
    assert published is not None
    assert published.class_name == "Temperature"
    assert len(published.centroids.as_dict()) == 6

    known = application.processing_runtime.process(_profile("D"))
    assert known.decision.state is SemanticClassDecisionState.KNOWN
    assert known.decision.candidate.class_id == "temperature"

    application.constraint_store.upsert(
        NegativeMembershipConstraint("D", "Temperature")
    )
    blocked = application.processing_runtime.process(
        _profile("D", {"reading": 1.0, "quality": 1.0})
    )
    assert blocked.decision.state is SemanticClassDecisionState.UNKNOWN
    assert blocked.decision.reasons == (
        SemanticClassDecisionReason.ALL_CLASSES_BLOCKED,
    )
    assert application.unknown_pool.get("D") is not None

    application.constraint_store.upsert(NegativeMembershipConstraint("D", "Other"))
    correction = UnknownClusterCandidate("schema", 2, ("D",))
    application.review_runtime.register_candidate(correction)
    application.review_runtime.apply_review(
        _review(CandidateIdentity.from_candidate(correction), "Temperature", ("D",)),
        "temperature",
    )
    assert application.known_class_registry.get("temperature") is not published
    assert not application.constraint_store.is_blocked("D", "Temperature")
    assert application.constraint_store.is_blocked("D", "Other")

    eligible_again = application.processing_runtime.process(
        _profile("D", {"reading": 1.0, "quality": 1.0, "status": 1.0})
    )
    assert eligible_again.decision.state is SemanticClassDecisionState.KNOWN
    assert eligible_again.decision.candidate.class_id == "temperature"
