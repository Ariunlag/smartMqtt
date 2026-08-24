"""Focused durable semantic-state serialization and lifecycle tests."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from main import create_app
from models.mqtt_message import MQTTMessage
from services.embedding.base_model import BaseEmbeddingModel
from services.semantic import (
    CandidateConfirmationSource,
    CandidateMembershipReview,
    HDBSCANDiscoveryConfig,
    InMemorySemanticStateRepository,
    PostgresSemanticStateRepository,
    RepresentationClassConsensus,
    SemanticClassDecision,
    SemanticClassDecisionConfig,
    SemanticClassDecisionPolicy,
    SemanticClassDecisionReason,
    SemanticClassDecisionState,
    SemanticDiscoveryConfig,
    SemanticPersistenceCompatibilityError,
    SemanticPersistenceConfig,
    SemanticPersistenceRecord,
    SemanticSnapshotSerializer,
    SemanticSnapshotValidationError,
    StreamProfiler,
    build_semantic_application,
)


class DeterministicModel(BaseEmbeddingModel):
    def encode(self, texts):
        return [[float(index + 1), 1.0] for index, _ in enumerate(texts)]


def _application(repository=None, *, enabled=False, fingerprint="model-fp"):
    return build_semantic_application(
        embedding_model=DeterministicModel(),
        known_classes=(),
        decision_policy=SemanticClassDecisionPolicy(
            SemanticClassDecisionConfig(1, 0.0, 0.0, -1.0)
        ),
        persistence_repository=repository,
        persistence_config=SemanticPersistenceConfig(
            enabled=enabled,
            save_debounce_seconds=0.001,
            save_timeout=0.5,
            restore_timeout=0.5,
            shutdown_flush_timeout=0.5,
        ),
        model_fingerprint=fingerprint,
    )


def _restart_application(repository):
    return build_semantic_application(
        embedding_model=DeterministicModel(),
        known_classes=(),
        decision_policy=SemanticClassDecisionPolicy(
            SemanticClassDecisionConfig(1, 0.8, 0.0, 0.2)
        ),
        hdbscan_config=HDBSCANDiscoveryConfig(
            min_cluster_size=2,
            min_samples=1,
            allow_single_cluster=True,
        ),
        discovery_config=SemanticDiscoveryConfig(debounce_seconds=0.001),
        persistence_repository=repository,
        persistence_config=SemanticPersistenceConfig(
            enabled=True,
            save_debounce_seconds=0.001,
            save_timeout=1.0,
            restore_timeout=1.0,
            shutdown_flush_timeout=1.0,
        ),
        model_fingerprint="restart-model-fp",
    )


def _populated(repository=None, *, enabled=False, fingerprint="model-fp"):
    application = _application(repository, enabled=enabled, fingerprint=fingerprint)
    application.processing_runtime.process(
        StreamProfiler().profile(
            "factory/line/temperature",
            {"unit": "celsius", "site": "north"},
            {"value": 21.5},
        )
    )
    return application


def test_schema_version_and_complete_empty_application_round_trip():
    application = _application()
    serializer = SemanticSnapshotSerializer()
    snapshot = application.snapshot()

    record = serializer.serialize(snapshot)
    restored = serializer.deserialize(record, expected_model_fingerprint="model-fp")

    assert record.schema_version == 3
    assert restored == snapshot
    assert restored.runtime_states == ()


def test_version_one_snapshot_migrates_with_empty_confirmed_memberships():
    serializer = SemanticSnapshotSerializer()
    current = serializer.serialize(_application().snapshot())
    legacy_payload = dict(current.payload)
    legacy_payload.pop("confirmed_memberships")
    legacy_payload.pop("semantic_context_generation")
    legacy = replace(current, schema_version=1, payload=legacy_payload)

    restored = serializer.deserialize(
        legacy,
        expected_model_fingerprint="model-fp",
    )

    assert restored.metadata.schema_version == 3
    assert restored.confirmed_memberships == ()
    assert restored.semantic_context_generation == 1


def test_version_two_snapshot_marks_cached_decisions_stale_and_drops_unknown_evidence():
    serializer = SemanticSnapshotSerializer()
    current = serializer.serialize(_populated().snapshot())
    legacy_payload = dict(current.payload)
    legacy_payload.pop("semantic_context_generation")
    legacy_states = []
    for state in legacy_payload["runtime_states"]:
        state = dict(state)
        state.pop("semantic_context_generation")
        decision = dict(state["decision"])
        decision.pop("confirmed_class_id")
        decision.pop("confirmed_class_name")
        state["decision"] = decision
        legacy_states.append(state)
    legacy_payload["runtime_states"] = legacy_states
    legacy = replace(current, schema_version=2, payload=legacy_payload)

    restored = serializer.deserialize(
        legacy,
        expected_model_fingerprint="model-fp",
    )

    assert restored.metadata.schema_version == 3
    assert restored.semantic_context_generation == 1
    assert restored.runtime_states[0].semantic_context_generation == 0
    assert restored.unknown_pool.entries == ()
    assert restored.pending_candidates == ()


def test_runtime_temporal_six_view_evidence_consensus_and_unknown_round_trip():
    application = _populated()
    snapshot = application.snapshot()
    restored = SemanticSnapshotSerializer().deserialize(
        SemanticSnapshotSerializer().serialize(snapshot),
        expected_model_fingerprint="model-fp",
    )

    assert restored == snapshot
    state = restored.runtime_states[0]
    assert state.temporal_profile.observation_count == 1
    assert len(state.representations.as_dict()) == 6
    assert len(state.embeddings.as_dict()) == 6
    assert state.evidence.rows == ()
    assert state.consensus.classes == ()
    assert state.decision.state.value == "UNKNOWN"
    assert restored.unknown_pool.version == snapshot.unknown_pool.version


@pytest.mark.parametrize(
    ("state", "reason"),
    [
        (
            SemanticClassDecisionState.KNOWN,
            SemanticClassDecisionReason.KNOWN_CRITERIA_MET,
        ),
        (
            SemanticClassDecisionState.UNCERTAIN,
            SemanticClassDecisionReason.BELOW_KNOWN_SIMILARITY,
        ),
    ],
)
def test_known_and_uncertain_runtime_decisions_round_trip(state, reason):
    snapshot = _populated().snapshot()
    runtime_state = snapshot.runtime_states[0]
    candidate = RepresentationClassConsensus("class-1", "Class One", 6, 1.0, 0.9)
    decision = SemanticClassDecision(state, candidate, None, None, (reason,))
    changed = replace(
        snapshot,
        runtime_states=(replace(runtime_state, decision=decision),),
    )
    serializer = SemanticSnapshotSerializer()
    restored = serializer.deserialize(
        serializer.serialize(changed), expected_model_fingerprint="model-fp"
    )
    assert restored.runtime_states[0].decision == decision


@pytest.mark.parametrize("field", ["schema_version", "model", "contract"])
def test_incompatible_schema_model_and_contract_are_rejected(field):
    serializer = SemanticSnapshotSerializer()
    record = serializer.serialize(_application().snapshot())
    if field == "schema_version":
        record = replace(record, schema_version=4)
        error = SemanticSnapshotValidationError
        kwargs = {"expected_model_fingerprint": "model-fp"}
    elif field == "model":
        error = SemanticPersistenceCompatibilityError
        kwargs = {"expected_model_fingerprint": "other"}
    else:
        error = SemanticPersistenceCompatibilityError
        kwargs = {
            "expected_model_fingerprint": "model-fp",
            "expected_representation_contract_version": "other",
        }
    with pytest.raises(error):
        serializer.deserialize(record, **kwargs)


def test_non_finite_and_inconsistent_vectors_are_rejected():
    application = _populated()
    snapshot = application.snapshot()
    state = snapshot.runtime_states[0]
    bad_nan = replace(
        state.embeddings,
        value_only=(float("nan"), 1.0),
    )
    with pytest.raises(SemanticSnapshotValidationError, match="finite"):
        SemanticSnapshotSerializer().serialize(
            replace(snapshot, runtime_states=(replace(state, embeddings=bad_nan),))
        )

    bad_dimension = replace(state.embeddings, value_only=(1.0,))
    with pytest.raises(SemanticSnapshotValidationError, match="dimension"):
        SemanticSnapshotSerializer().serialize(
            replace(
                snapshot, runtime_states=(replace(state, embeddings=bad_dimension),)
            )
        )


def test_duplicate_and_missing_payload_identities_are_rejected():
    serializer = SemanticSnapshotSerializer()
    snapshot = _populated().snapshot()
    with pytest.raises(SemanticSnapshotValidationError, match="Duplicate runtime"):
        serializer.serialize(
            replace(snapshot, runtime_states=snapshot.runtime_states * 2)
        )

    record = serializer.serialize(snapshot)
    payload = dict(record.payload)
    payload.pop("runtime_states")
    with pytest.raises(SemanticSnapshotValidationError, match="missing"):
        serializer.deserialize(
            replace(record, payload=payload),
            expected_model_fingerprint="model-fp",
        )


def test_restore_preserves_shared_objects_and_exact_state():
    source = _populated()
    target = _application()
    identities = (
        target.unknown_pool,
        target.processing_runtime.state_store,
        target.evidence_store,
        target.constraint_store,
        target.known_class_registry,
        target.class_catalog,
    )

    target.restore(source.snapshot())

    assert target.snapshot() == source.snapshot()
    assert identities == (
        target.unknown_pool,
        target.processing_runtime.state_store,
        target.evidence_store,
        target.constraint_store,
        target.known_class_registry,
        target.class_catalog,
    )
    assert target.processing_runtime.unknown_pool is target.unknown_pool
    assert target.review_runtime.unknown_pool is target.unknown_pool
    assert target.discovery_service.unknown_pool is target.unknown_pool


def test_malformed_restore_does_not_mutate_live_state():
    application = _populated()
    before = application.snapshot()
    malformed = replace(before, runtime_states=before.runtime_states * 2)

    with pytest.raises(SemanticSnapshotValidationError):
        application.restore(malformed)

    assert application.snapshot() == before


def test_generation_increments_once_per_runtime_transaction_and_not_for_noop():
    application = _application()
    assert application.state_coordinator.generation == 0
    application.processing_runtime.process(
        StreamProfiler().profile("topic/one", {}, {"value": 1})
    )
    assert application.state_coordinator.generation == 1
    existing = application.unknown_pool.get("topic/one")
    application.unknown_pool.upsert(existing)
    assert application.state_coordinator.generation == 1


def test_in_memory_repository_generation_guard_and_isolation():
    serializer = SemanticSnapshotSerializer()
    repository = InMemorySemanticStateRepository()
    new = serializer.serialize(_populated().snapshot())
    old = replace(new, generation=max(0, new.generation - 1))

    assert repository.save(new)
    assert not repository.save(old)
    assert repository.load("default").generation == new.generation
    assert InMemorySemanticStateRepository().load("default") is None


@pytest.mark.asyncio
async def test_persistence_service_coalesces_and_restart_recovers():
    repository = InMemorySemanticStateRepository()
    first = _application(repository, enabled=True)
    assert first.persistence_service.status().running is False
    assert await first.persistence_service.restore() is False
    await first.persistence_service.start()
    await first.persistence_service.start()
    first.processing_runtime.process(
        StreamProfiler().profile("topic/restart", {"unit": "c"}, {"value": 4})
    )
    for _ in range(20):
        first.persistence_service.request_save()
    assert await first.persistence_service.flush()
    assert first.persistence_service.status().save_count == 1
    await first.persistence_service.stop()

    second = _application(repository, enabled=True)
    assert await second.persistence_service.restore()
    assert second.processing_runtime.state_store.get("topic/restart") is not None
    assert second.unknown_pool.version == first.unknown_pool.version


@pytest.mark.asyncio
async def test_save_runs_on_worker_thread_and_failed_save_remains_dirty_for_retry():
    class FlakyRepository(InMemorySemanticStateRepository):
        def __init__(self):
            super().__init__()
            self.fail = True
            self.thread_ids = []

        def save(self, record):
            import threading

            self.thread_ids.append(threading.get_ident())
            if self.fail:
                raise RuntimeError("temporary database failure")
            return super().save(record)

    import threading

    event_loop_thread = threading.get_ident()
    repository = FlakyRepository()
    application = _application(repository, enabled=True)
    await application.persistence_service.restore()
    await application.persistence_service.start()
    application.processing_runtime.process(
        StreamProfiler().profile("topic/flaky", {}, {"value": 1})
    )
    assert not await application.persistence_service.flush()
    status = application.persistence_service.status()
    assert status.failed_save_count >= 1
    assert status.save_pending

    repository.fail = False
    application.persistence_service.request_save()
    assert await application.persistence_service.flush()
    assert all(thread_id != event_loop_thread for thread_id in repository.thread_ids)
    await application.persistence_service.stop()


def test_postgres_repository_uses_parameterized_sql_and_no_constructor_io():
    class Cursor:
        rowcount = 1

    class Connection:
        def __init__(self, owner):
            self.owner = owner

        def execute(self, sql, params):
            self.owner.calls.append((sql, params))
            return Cursor()

    class Client:
        def __init__(self):
            self.calls = []

        @contextmanager
        def transaction(self):
            yield Connection(self)

        def fetch_one(self, sql, params):
            self.calls.append((sql, params))

    client = Client()
    repository = PostgresSemanticStateRepository(client)
    assert client.calls == []
    assert repository.load("default") is None
    record = SemanticPersistenceRecord(
        "default", 1, 3, "fp", "contract", {}, {}, datetime.now(timezone.utc)
    )
    assert repository.save(record)
    assert client.calls[0][1] == ("default",)
    assert client.calls[1][1][0] == "default"
    assert "%s" in client.calls[1][0]
    assert "CREATE TABLE" not in client.calls[1][0]


def test_persistence_status_endpoint_is_vector_free_and_uses_application_state():
    application = _populated()
    app = create_app(semantic_application=application, manage_services=False)
    with TestClient(app) as client:
        response = client.get("/api/semantic-review/persistence-status")

    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == 3
    assert body["current_generation"] == 1
    assert "payload" not in body
    assert "vectors" not in body
    assert "dsn" not in body


def test_persistence_retry_endpoint_requests_current_generation_without_state_data():
    application = _application(InMemorySemanticStateRepository(), enabled=True)
    app = create_app(semantic_application=application, manage_services=False)
    with TestClient(app) as client:
        response = client.post("/api/semantic-review/persistence-retry")

    assert response.status_code == 200
    assert response.json() == {"accepted": True, "current_generation": 0}
    assert application.persistence_service.status().save_pending
    assert "payload" not in response.text.lower()
    assert "dsn" not in response.text.lower()


def test_importing_main_does_not_construct_persistence_or_perform_io():
    import main

    assert getattr(main.app.state, "semantic_application", None) is None


@pytest.mark.asyncio
async def test_full_restart_recovers_reviewed_class_constraints_and_discovery_state():
    repository = InMemorySemanticStateRepository()
    first = _restart_application(repository)
    await first.persistence_service.restore()
    await first.persistence_service.start()
    await first.discovery_service.start()
    await first.processing_service.start()

    for topic in ("related/A", "related/B", "related/C"):
        first.processing_service.submit(
            MQTTMessage(
                topic=topic,
                tags={"site": "lab"},
                fields={"reading": 1.0},
                timestamp="2026-01-01T00:00:00Z",
            )
        )
    await _wait_for(lambda: first.processing_service.status().processed_count == 3)
    await _wait_for(lambda: len(first.review_runtime.list_candidates()) == 6)
    candidate = next(
        item
        for item in first.review_runtime.list_candidates()
        if item.identity.representation_name == "key_value"
    )
    first.review_runtime.apply_review(
        CandidateMembershipReview(
            identity=candidate.identity,
            semantic_class_name="Related Sensor",
            kept_topics=("related/B", "related/C"),
            removed_topics=("related/A",),
            added_topics=(),
            source=CandidateConfirmationSource.HUMAN,
        ),
        "related-sensor",
    )
    snapshot_a = first.snapshot()
    assert first.known_class_registry.get("related-sensor") is not None
    assert first.constraint_store.is_blocked("related/A", "Related Sensor")
    assert tuple(
        membership.topic for membership in first.confirmed_membership_store.snapshot()
    ) == ("related/B", "related/C")
    assert await first.persistence_service.flush()
    await first.processing_service.stop()
    await first.discovery_service.stop()
    await first.persistence_service.stop()

    second = _restart_application(repository)
    assert await second.persistence_service.restore()
    restored = second.snapshot()
    assert restored.runtime_states == snapshot_a.runtime_states
    assert restored.unknown_pool == snapshot_a.unknown_pool
    assert restored.trusted_evidence == snapshot_a.trusted_evidence
    assert restored.constraints == snapshot_a.constraints
    assert restored.confirmed_memberships == snapshot_a.confirmed_memberships
    assert restored.known_classes == snapshot_a.known_classes
    assert restored.class_catalog == snapshot_a.class_catalog
    assert restored.pending_candidates == snapshot_a.pending_candidates
    assert restored.suppressed_candidates == snapshot_a.suppressed_candidates

    await second.persistence_service.start()
    await second.discovery_service.start()
    await second.processing_service.start()
    second.processing_service.submit(
        MQTTMessage(
            topic="related/D",
            tags={"site": "lab"},
            fields={"reading": 1.0},
            timestamp="2026-01-01T00:00:01Z",
        )
    )
    await _wait_for(lambda: second.processing_service.status().processed_count == 1)
    assert (
        second.processing_runtime.state_store.get("related/D").decision.state
        is SemanticClassDecisionState.KNOWN
    )

    second.processing_service.submit(
        MQTTMessage(
            topic="related/A",
            tags={"site": "changed"},
            fields={"reading": 1.0},
            timestamp="2026-01-01T00:00:02Z",
        )
    )
    await _wait_for(lambda: second.processing_service.status().processed_count == 2)
    assert (
        second.processing_runtime.state_store.get("related/A").decision.state
        is SemanticClassDecisionState.UNKNOWN
    )
    published = second.discovery_service.status().published_count
    second.discovery_service.request()
    await _wait_for(
        lambda: second.discovery_service.status().published_count > published
    )
    assert candidate.identity not in {
        item.identity for item in second.review_runtime.list_candidates()
    }

    await second.processing_service.stop()
    await second.discovery_service.stop()
    await second.persistence_service.stop()


async def _wait_for(predicate, timeout=5.0):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.01)
