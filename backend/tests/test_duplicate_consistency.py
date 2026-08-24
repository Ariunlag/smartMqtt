import math
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from types import SimpleNamespace

import pytest
from services.dupe_manager import DupeManager
from services.duplicate.canonicalization_service import (
    DuplicateCanonicalizationConflict,
    DuplicateCanonicalizationService,
)
from services.duplicate.duplicate_service import DuplicateService
from services.embedding.base_model import BaseEmbeddingModel
from services.mqtt.handlers.canonical_identity_handler import CanonicalIdentityHandler
from services.semantic.candidate_confirmation import CandidateIdentity
from services.semantic.confirmed_membership import ConfirmedSemanticMembership
from services.semantic.known_class_assembly import KnownClassAssemblyRequest
from services.semantic.known_class_registry import SemanticClassDefinition
from services.semantic.representation_embedder import RepresentationEmbeddings
from services.semantic.semantic_application import build_semantic_application
from services.semantic.semantic_class_decision import (
    SemanticClassDecisionConfig,
    SemanticClassDecisionPolicy,
)
from services.semantic.semantic_feedback_workflow import NegativeMembershipConstraint
from services.semantic.semantic_review_runtime import (
    PendingSemanticCandidate,
    SemanticReviewRuntime,
    SemanticReviewStateSnapshot,
)
from services.semantic.stream_profiler import StreamProfiler
from services.semantic.trusted_class_evidence import TrustedClassEvidence
from services.store.canonical_identity_store import CanonicalIdentityStore
from services.store.embedding_store import TopicEmbeddingStore
from services.store.relation_store import ClassStore
from services.topic_manager import DuplicateAliasSubscriptionError, TopicManager


class FakeDupeStore:
    def __init__(self):
        self.rows = {}
        self.lock = Lock()

    @staticmethod
    def _key(a, b):
        return tuple(sorted((a, b)))

    def create_pending(self, a, b, score):
        with self.lock:
            key = self._key(a, b)
            created = key not in self.rows
            self.rows.setdefault(
                key, {"topics": list(key), "score": score, "status": "PENDING"}
            )
            return self.rows[key], created

    def get_pair(self, a, b):
        return self.rows.get(self._key(a, b))

    def update_status(self, a, b, status):
        row = self.get_pair(a, b)
        if row:
            row["status"] = status
        return row

    def get_all(self):
        return list(self.rows.values())


class FakeCursor:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def fetchall(self):
        return self.rows


class FakeMergeConnection:
    def __init__(self):
        self.identities = {}

    def execute(self, sql, params=()):
        normalized = " ".join(sql.split())
        if "SELECT pg_advisory" in normalized:
            return FakeCursor()
        if "WHERE topic = ANY" in normalized:
            return FakeCursor(
                {"topic": topic, "canonical_topic": self.identities[topic]}
                for topic in params[0]
                if topic in self.identities
            )
        if "WHERE canonical_topic = ANY" in normalized:
            return FakeCursor(
                {"topic": topic, "canonical_topic": root}
                for topic, root in self.identities.items()
                if root in params[0]
            )
        if "INSERT INTO duplicate_canonical_topics" in normalized:
            winner, winner_root, loser, loser_root = params
            self.identities.setdefault(winner, winner_root)
            self.identities.setdefault(loser, loser_root)
            return FakeCursor()
        if "UPDATE duplicate_canonical_topics" in normalized:
            winner, loser = params
            for topic, root in tuple(self.identities.items()):
                if root == loser:
                    self.identities[topic] = winner
            return FakeCursor()
        raise AssertionError(normalized)


class NoDatabase:
    pass


class ConstantModel(BaseEmbeddingModel):
    def encode(self, texts):
        return [(1.0, 0.0) for _ in texts]


def semantic_application():
    return build_semantic_application(
        embedding_model=ConstantModel(),
        known_classes=(),
        decision_policy=SemanticClassDecisionPolicy(
            SemanticClassDecisionConfig(1, 0.8, 0.0, 0.2)
        ),
    )


def prepare_semantic_class(application, topics=("A", "B")):
    profiler = StreamProfiler()
    for index, topic in enumerate(topics):
        application.processing_runtime.process(
            profiler.profile(topic, {}, {"reading": float(index + 1)})
        )
    for representation in RepresentationEmbeddings.__dataclass_fields__:
        application.evidence_store.upsert(
            TrustedClassEvidence("Temperature", representation, (1.0, 0.0), topics)
        )
    application.class_catalog.register(
        SemanticClassDefinition("temperature", "Temperature")
    )
    assembly = application.review_runtime.assembler.assemble(
        KnownClassAssemblyRequest("temperature", "Temperature"),
        application.evidence_store,
    )
    application.known_class_registry.upsert(assembly.centroids)


def test_terminal_duplicate_decisions_are_not_reopened_or_republished():
    store = FakeDupeStore()
    manager = DupeManager(store=store)
    first, created = manager.create_candidate("b", "a", 0.9)
    assert created is True
    assert first["topics"] == ["a", "b"]

    store.update_status("a", "b", "NOT_DUPLICATE")
    terminal, created = manager.create_candidate("a", "b", 0.99)
    assert created is False
    assert terminal["status"] == "NOT_DUPLICATE"

    store.rows[("c", "d")] = {
        "topics": ["c", "d"],
        "score": 1.0,
        "status": "CONFIRMED_DUPLICATE",
    }
    terminal, created = manager.create_candidate("d", "c", 0.99)
    assert created is False
    assert terminal["status"] == "CONFIRMED_DUPLICATE"


def test_concurrent_pending_candidate_creation_is_one_logical_event():
    manager = DupeManager(store=FakeDupeStore())
    with ThreadPoolExecutor(max_workers=8) as executor:
        outcomes = tuple(
            executor.map(
                lambda order: manager.create_candidate(*order, 0.95),
                (("A", "B"), ("B", "A")) * 20,
            )
        )
    assert sum(created for _, created in outcomes) == 1
    assert {tuple(record["topics"]) for record, _ in outcomes} == {("A", "B")}


def test_canonical_merges_collapse_chains_and_merge_existing_sets():
    store = CanonicalIdentityStore(NoDatabase())
    conn = FakeMergeConnection()

    first = store.merge(conn, "A", "B")
    second = store.merge(conn, "A", "C")
    store.merge(conn, "D", "E")
    merged = store.merge(conn, "A", "D")

    assert first.canonical_topic == second.canonical_topic == "A"
    assert merged.aliases == ("D", "E")
    assert conn.identities == {"A": "A", "B": "A", "C": "A", "D": "A", "E": "A"}


@pytest.mark.asyncio
async def test_duplicate_numerical_safety(monkeypatch):
    service = DuplicateService(min_points=2)
    assert service.cosine([0.0, 0.0], [1.0, 2.0]) == 0.0

    async def constant_points(topic, limit):
        return [
            {"time": "1", "value": 4.0},
            {"time": "2", "value": 4.0},
        ]

    monkeypatch.setattr(
        "services.duplicate.duplicate_service.query_manager.get_last_points",
        constant_points,
    )
    score = await service.hybrid_score("a", [1.0], "b", [1.0])
    assert math.isfinite(score)


@pytest.mark.asyncio
async def test_alias_message_stops_before_active_pipeline():
    identity_store = SimpleNamespace(
        get=lambda topic: SimpleNamespace(is_alias=True, canonical_topic="canonical")
    )
    handler = CanonicalIdentityHandler(identity_store)
    assert await handler.handle_message(SimpleNamespace(topic="alias")) is False


def test_manual_subscribe_cannot_reactivate_alias():
    identity_store = SimpleNamespace(
        get=lambda topic: SimpleNamespace(is_alias=True, canonical_topic="canonical")
    )
    with pytest.raises(DuplicateAliasSubscriptionError, match="canonical"):
        TopicManager(identity_store).subscribe("alias")


def test_pending_semantic_candidates_containing_alias_are_invalidated():
    runtime = SemanticReviewRuntime()
    stale = PendingSemanticCandidate(CandidateIdentity("value_only", ("A", "B")))
    retained = PendingSemanticCandidate(CandidateIdentity("value_only", ("C", "D")))
    runtime.replace_review_state(SemanticReviewStateSnapshot((stale, retained), ()))

    removed = runtime.invalidate_topics(("B",))

    assert removed == (stale,)
    assert runtime.list_candidates() == (retained,)


def test_same_class_membership_and_prototype_are_deduplicated_to_canonical():
    application = semantic_application()
    prepare_semantic_class(application)
    for topic in ("A", "B"):
        application.confirmed_membership_store.upsert(
            ConfirmedSemanticMembership(topic, "temperature", "Temperature")
        )

    service = DuplicateCanonicalizationService(None, None)
    service._preflight_semantics(application, "A", ("B",))
    service._reconcile_semantics(application, "A", ("B",))

    assert application.confirmed_membership_store.get("B") is None
    assert application.confirmed_membership_store.get("A") is not None
    assert all(
        evidence.member_topics == ("A",) and evidence.member_count == 1
        for evidence in application.evidence_store.all()
    )


def test_alias_human_membership_and_constraints_transfer_to_canonical():
    application = semantic_application()
    prepare_semantic_class(application, topics=("B",))
    application.confirmed_membership_store.upsert(
        ConfirmedSemanticMembership("B", "temperature", "Temperature")
    )
    application.constraint_store.upsert(NegativeMembershipConstraint("B", "Humidity"))

    service = DuplicateCanonicalizationService(None, None)
    service._preflight_semantics(application, "A", ("B",))
    service._reconcile_semantics(application, "A", ("B",))

    assert application.confirmed_membership_store.get("A").class_id == "temperature"
    assert application.confirmed_membership_store.get("B") is None
    assert application.constraint_store.is_blocked("A", "Humidity")
    assert not application.constraint_store.is_blocked("B", "Humidity")
    assert all(
        evidence.member_topics == ("A",)
        for evidence in application.evidence_store.all()
    )


def test_conflicting_human_memberships_reject_without_mutation():
    application = semantic_application()
    application.confirmed_membership_store.upsert(
        ConfirmedSemanticMembership("A", "temperature", "Temperature")
    )
    application.confirmed_membership_store.upsert(
        ConfirmedSemanticMembership("B", "humidity", "Humidity")
    )
    before = application.confirmed_membership_store.snapshot()

    with pytest.raises(DuplicateCanonicalizationConflict, match="Conflicting"):
        DuplicateCanonicalizationService(None, None)._preflight_semantics(
            application, "A", ("B",)
        )

    assert application.confirmed_membership_store.snapshot() == before


def test_transferred_negative_constraint_cannot_conflict_with_positive_membership():
    application = semantic_application()
    application.confirmed_membership_store.upsert(
        ConfirmedSemanticMembership("A", "temperature", "Temperature")
    )
    application.constraint_store.upsert(
        NegativeMembershipConstraint("B", "Temperature")
    )

    with pytest.raises(DuplicateCanonicalizationConflict, match="Negative"):
        DuplicateCanonicalizationService(None, None)._preflight_semantics(
            application, "A", ("B",)
        )


def test_keep_both_topics_can_share_one_semantic_class():
    application = semantic_application()
    for topic in ("A", "B"):
        application.confirmed_membership_store.upsert(
            ConfirmedSemanticMembership(topic, "temperature", "Temperature")
        )
    assert tuple(
        membership.topic for membership in application.confirmed_membership_store.all()
    ) == ("A", "B")


def test_qdrant_candidates_exclude_aliases_without_limit_plus_one(monkeypatch):
    points = [
        SimpleNamespace(payload={"topic": f"alias/{i}"}, vector=[1.0])
        for i in range(20)
    ] + [SimpleNamespace(payload={"topic": "active"}, vector=[0.9])]
    observed = {}

    def nearest_many(collection, vector, limit):
        observed["limit"] = limit
        return points

    monkeypatch.setattr(
        "services.store.embedding_store.qdrant_client.nearest_many", nearest_many
    )

    class Identities:
        def resolve_many(self, topics):
            return {
                topic: ("root" if topic.startswith("alias/") else topic)
                for topic in topics
            }

    candidates = TopicEmbeddingStore(Identities()).candidates_for(
        "source", [1.0], limit=10
    )
    assert [candidate["topic"] for candidate in candidates] == ["active"]
    assert observed["limit"] == 80


def test_user_class_writes_canonicalize_and_deduplicate_aliases():
    identities = SimpleNamespace(
        resolve_many=lambda topics: {"A": "A", "B": "A", "C": "C"}
    )
    assert ClassStore(identities)._canonicalize(["B", "A", "C", "B"]) == [
        "A",
        "C",
    ]
