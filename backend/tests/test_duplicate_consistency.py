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
from services.mqtt.handlers.canonical_identity_handler import CanonicalIdentityHandler
from services.store.canonical_identity_store import CanonicalIdentityStore
from services.store.embedding_store import TopicEmbeddingStore
from services.store.relation_store import ClassStore
from services.topic_manager import DuplicateAliasSubscriptionError, TopicManager


class FakeDupeStore:
    def __init__(self):
        self.rows = {}
        self.lock = Lock()

    @staticmethod
    def key(left, right):
        return tuple(sorted((left, right)))

    def create_pending(self, left, right, score):
        with self.lock:
            key = self.key(left, right)
            created = key not in self.rows
            self.rows.setdefault(
                key, {"topics": list(key), "score": score, "status": "PENDING"}
            )
            return self.rows[key], created

    def get_pair(self, left, right):
        return self.rows.get(self.key(left, right))

    def update_status(self, left, right, status):
        row = self.get_pair(left, right)
        if row:
            row["status"] = status
        return row

    def get_all(self):
        return list(self.rows.values())


def test_terminal_duplicate_decisions_are_not_reopened():
    store = FakeDupeStore()
    manager = DupeManager(store=store)
    _, created = manager.create_candidate("b", "a", 0.9)
    assert created is True
    store.update_status("a", "b", "NOT_DUPLICATE")
    terminal, created = manager.create_candidate("a", "b", 0.99)
    assert created is False
    assert terminal["status"] == "NOT_DUPLICATE"


def test_concurrent_pending_candidate_creation_is_one_event():
    manager = DupeManager(store=FakeDupeStore())
    with ThreadPoolExecutor(max_workers=8) as executor:
        outcomes = tuple(
            executor.map(
                lambda order: manager.create_candidate(*order, 0.95),
                (("A", "B"), ("B", "A")) * 20,
            )
        )
    assert sum(created for _, created in outcomes) == 1


@pytest.mark.asyncio
async def test_duplicate_numerical_safety(monkeypatch):
    service = DuplicateService(min_points=2)
    assert service.cosine([0.0, 0.0], [1.0, 2.0]) == 0.0

    async def constant_points(topic, limit):
        return [{"time": "1", "value": 4.0}, {"time": "2", "value": 4.0}]

    monkeypatch.setattr(
        "services.duplicate.duplicate_service.query_manager.get_last_points",
        constant_points,
    )
    assert math.isfinite(await service.hybrid_score("a", [1.0], "b", [1.0]))


@pytest.mark.asyncio
async def test_alias_message_stops_before_active_pipeline():
    identity_store = SimpleNamespace(
        get=lambda topic: SimpleNamespace(is_alias=True, canonical_topic="canonical")
    )
    assert (
        await CanonicalIdentityHandler(identity_store).handle_message(
            SimpleNamespace(topic="alias")
        )
        is False
    )


def test_manual_subscribe_cannot_reactivate_alias():
    identity_store = SimpleNamespace(
        get=lambda topic: SimpleNamespace(is_alias=True, canonical_topic="canonical")
    )
    with pytest.raises(DuplicateAliasSubscriptionError, match="canonical"):
        TopicManager(identity_store).subscribe("alias")


def test_keep_both_topics_remain_independent_and_class_eligible():
    store = FakeDupeStore()
    manager = DupeManager(store=store)
    manager.create_candidate("A", "B", 0.9)
    result = manager.keep_both("A", "B")
    assert result["status"] == "NOT_DUPLICATE"


def test_class_writes_canonicalize_and_deduplicate_aliases():
    identities = SimpleNamespace(
        resolve_many=lambda topics: {"A": "A", "B": "A", "C": "C"}
    )
    assert ClassStore(identities)._canonicalize(["B", "A", "C", "B"]) == [
        "A",
        "C",
    ]


def test_qdrant_duplicate_candidates_exclude_aliases(monkeypatch):
    points = [
        SimpleNamespace(payload={"topic": f"alias/{index}"}, vector=[1.0])
        for index in range(20)
    ] + [SimpleNamespace(payload={"topic": "active"}, vector=[0.9])]
    monkeypatch.setattr(
        "services.store.embedding_store.qdrant_client.nearest_many",
        lambda collection, vector, limit: points,
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


class MembershipCursor:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows


class MembershipConnection:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, sql, params):
        return MembershipCursor(self.rows)


def test_conflicting_explicit_class_memberships_block_canonicalization():
    conn = MembershipConnection(
        [
            {"topic": "A", "classes": ["Temperature"]},
            {"topic": "B", "classes": ["Humidity"]},
        ]
    )
    with pytest.raises(DuplicateCanonicalizationConflict, match="class memberships"):
        DuplicateCanonicalizationService._preflight_class_membership(conn, "A", "B")


def test_duplicate_reconciliation_bumps_affected_class_versions_in_transaction():
    class VersionConnection:
        def __init__(self):
            self.updated = None

        def execute(self, sql, params):
            normalized = " ".join(sql.split())
            if "SELECT DISTINCT class_name" in normalized:
                return MembershipCursor([{"class_name": "Temperature"}])
            if "UPDATE classes SET profile_version" in normalized:
                self.updated = tuple(params[0])
                return MembershipCursor([])
            raise AssertionError(normalized)

    conn = VersionConnection()
    classes = DuplicateCanonicalizationService._classes_for_aliases(conn, ("B",))
    assert classes == ("Temperature",)
    DuplicateCanonicalizationService._bump_class_profile_versions(conn, classes)
    assert conn.updated == ("Temperature",)


def test_confirmed_duplicate_retry_repairs_derived_recommendation_state():
    store = FakeDupeStore()
    store.rows[store.key("A", "B")] = {
        "topics": ["A", "B"],
        "score": 0.99,
        "status": "CONFIRMED_DUPLICATE",
    }

    class Database:
        @staticmethod
        def fetch_all(sql, params):
            assert "duplicate_canonical_topics" in sql
            assert params == ("A", "A")
            return [{"topic": "B"}]

    class Identities:
        database = Database()

        @staticmethod
        def get(topic):
            assert topic == "B"
            return SimpleNamespace(is_alias=True, canonical_topic="A")

        @staticmethod
        def resolve_canonical(topic):
            assert topic == "A"
            return "A"

    class Application:
        def __init__(self):
            self.calls = []

        def canonicalized(self, canonical, aliases):
            self.calls.append((canonical, aliases))

    application = Application()
    service = DuplicateCanonicalizationService(Identities(), store)
    result = service.confirm(
        "A", "B", "B", recommendation_application=application
    )

    assert result.canonical_topic == "A"
    assert application.calls == [("A", ("B",))]


def test_canonical_identity_store_never_persists_alias_chains():
    class Database:
        pass

    class Cursor:
        def __init__(self, rows=()):
            self.rows = list(rows)

        def fetchall(self):
            return self.rows

    class Connection:
        def __init__(self):
            self.identities = {}

        def execute(self, sql, params=()):
            normalized = " ".join(sql.split())
            if "pg_advisory" in normalized:
                return Cursor()
            if "WHERE topic = ANY" in normalized:
                return Cursor(
                    {"topic": topic, "canonical_topic": self.identities[topic]}
                    for topic in params[0]
                    if topic in self.identities
                )
            if "WHERE canonical_topic = ANY" in normalized:
                return Cursor(
                    {"topic": topic, "canonical_topic": root}
                    for topic, root in self.identities.items()
                    if root in params[0]
                )
            if "INSERT INTO duplicate_canonical_topics" in normalized:
                winner, winner_root, loser, loser_root = params
                self.identities.setdefault(winner, winner_root)
                self.identities.setdefault(loser, loser_root)
                return Cursor()
            if "UPDATE duplicate_canonical_topics" in normalized:
                winner, loser = params
                for topic, root in tuple(self.identities.items()):
                    if root == loser:
                        self.identities[topic] = winner
                return Cursor()
            raise AssertionError(normalized)

    store = CanonicalIdentityStore(Database())
    conn = Connection()
    store.merge(conn, "A", "B")
    store.merge(conn, "A", "C")
    store.merge(conn, "D", "E")
    store.merge(conn, "A", "D")
    assert conn.identities == {"A": "A", "B": "A", "C": "A", "D": "A", "E": "A"}
