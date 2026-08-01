import asyncio
import threading
import time
from dataclasses import FrozenInstanceError, fields

import pytest
from models.mqtt_message import MQTTMessage
from services.embedding.base_model import BaseEmbeddingModel
from services.semantic import (
    RepresentationClassCentroids,
    RepresentationEmbeddings,
    SemanticClassDecisionConfig,
    SemanticClassDecisionPolicy,
    SemanticProcessingConfig,
    SemanticProcessingService,
    SemanticProcessingStatus,
    build_semantic_application,
)


class RecordingRuntime:
    def __init__(self, *, release=None, fail_topics=()):
        self.release = release
        self.fail_topics = set(fail_topics)
        self.profiles = []
        self.thread_ids = []

    def process(self, profile):
        self.profiles.append(profile)
        self.thread_ids.append(threading.get_ident())
        if self.release is not None:
            self.release.wait(timeout=2)
        if profile.topic in self.fail_topics:
            raise RuntimeError(f"forced failure for {profile.topic}")


class ConstantEmbeddingModel(BaseEmbeddingModel):
    def encode(self, texts):
        return [(1.0, 0.0) for _ in texts]


def _message(topic="sensor/a", fields_value=None):
    return MQTTMessage(
        topic=topic,
        tags={"site": "lab"},
        fields=fields_value or {"reading": 1.0},
        timestamp="2024-01-01T00:00:00Z",
    )


def _policy():
    return SemanticClassDecisionPolicy(SemanticClassDecisionConfig(1, 0.8, 0.0, 0.2))


def _known_class():
    vector = (1.0, 0.0)
    return RepresentationClassCentroids(
        class_id="temperature",
        class_name="Temperature",
        centroids=RepresentationEmbeddings(
            value_only=vector,
            key_only=vector,
            key_value=vector,
            schema=vector,
            numeric_key_only=vector,
            topic_key_value=vector,
        ),
    )


async def _wait_for(predicate, timeout=2.0):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.005)


def test_application_owns_one_unstarted_service_for_exact_runtime():
    application = build_semantic_application(
        embedding_model=ConstantEmbeddingModel(),
        known_classes=(),
        decision_policy=_policy(),
    )

    assert application.processing_service.runtime is application.processing_runtime
    assert application.processing_service.status().running is False
    assert application.processing_service._worker is None


async def test_start_is_idempotent_and_creates_exactly_one_worker():
    service = SemanticProcessingService(RecordingRuntime())

    await service.start()
    first_worker = service._worker
    await service.start()

    assert first_worker is not None
    assert service._worker is first_worker
    assert service.status().running is True
    await service.stop()


async def test_message_is_profiled_and_runtime_runs_off_event_loop_thread():
    runtime = RecordingRuntime()
    service = SemanticProcessingService(runtime)
    event_loop_thread = threading.get_ident()
    await service.start()

    assert service.submit(_message()) is True
    await _wait_for(lambda: service.status().processed_count == 1)
    await service.stop()

    profile = runtime.profiles[0]
    assert profile.topic == "sensor/a"
    assert tuple(item.key for item in profile.tags) == ("site",)
    assert tuple(item.key for item in profile.fields) == ("reading",)
    assert runtime.thread_ids == [runtime.thread_ids[0]]
    assert runtime.thread_ids[0] != event_loop_thread


async def test_submit_is_non_blocking_and_queue_full_is_counted_without_raising():
    release = threading.Event()
    runtime = RecordingRuntime(release=release)
    service = SemanticProcessingService(
        runtime,
        config=SemanticProcessingConfig(queue_max_size=1),
    )
    await service.start()

    started = time.perf_counter()
    assert service.submit(_message("first")) is True
    elapsed = time.perf_counter() - started
    await _wait_for(lambda: len(runtime.profiles) == 1)
    assert service.submit(_message("queued")) is True
    assert service.submit(_message("dropped")) is False
    assert elapsed < 0.05
    assert service.status().dropped_count == 1

    release.set()
    await service.stop()
    assert service.status().processed_count == 2


async def test_failure_is_recorded_and_next_message_still_succeeds():
    runtime = RecordingRuntime(fail_topics=("bad",))
    service = SemanticProcessingService(runtime)
    await service.start()

    assert service.submit(_message("bad")) is True
    assert service.submit(_message("good")) is True
    await _wait_for(
        lambda: service.status().failed_count + service.status().processed_count == 2
    )
    status = service.status()
    await service.stop()

    assert status.failed_count == 1
    assert status.processed_count == 1
    assert status.last_error_topic == "bad"
    assert "forced failure for bad" in status.last_error_message
    assert status.last_processed_topic == "good"


async def test_stop_drains_when_possible_and_timeout_is_bounded():
    draining = SemanticProcessingService(RecordingRuntime())
    await draining.start()
    for index in range(5):
        assert draining.submit(_message(f"drain/{index}")) is True
    await draining.stop()
    assert draining.status().processed_count == 5
    assert draining.status().running is False

    release = threading.Event()
    blocked = SemanticProcessingService(
        RecordingRuntime(release=release),
        config=SemanticProcessingConfig(shutdown_drain_timeout=0.02),
    )
    await blocked.start()
    assert blocked.submit(_message("blocked")) is True
    await _wait_for(lambda: len(blocked.runtime.profiles) == 1)
    started = time.perf_counter()
    await blocked.stop()
    elapsed = time.perf_counter() - started
    release.set()

    assert elapsed < 0.5
    assert blocked.status().running is False


async def test_live_sidecar_updates_shared_unknown_then_known_state():
    application = build_semantic_application(
        embedding_model=ConstantEmbeddingModel(),
        known_classes=(),
        decision_policy=_policy(),
    )
    service = application.processing_service
    await service.start()

    assert service.submit(_message("sensor/live")) is True
    await _wait_for(lambda: service.status().processed_count == 1)
    assert application.unknown_pool.get("sensor/live") is not None

    application.known_class_registry.upsert(_known_class())
    assert service.submit(_message("sensor/live", {"reading": 1.0, "quality": 1.0}))
    await _wait_for(lambda: service.status().processed_count == 2)
    await service.stop()

    assert application.unknown_pool.get("sensor/live") is None
    state = application.processing_runtime.state_store.get("sensor/live")
    assert state.decision.candidate.class_id == "temperature"


def test_status_is_immutable_payload_free_and_field_order_is_stable():
    status = SemanticProcessingService(RecordingRuntime()).status()

    assert isinstance(status, SemanticProcessingStatus)
    assert tuple(field.name for field in fields(status)) == (
        "running",
        "enabled",
        "queue_size",
        "queue_capacity",
        "submitted_count",
        "processed_count",
        "failed_count",
        "dropped_count",
        "last_processed_topic",
        "last_error_topic",
        "last_error_message",
    )
    assert not hasattr(status, "embeddings")
    assert not hasattr(status, "payload")
    with pytest.raises(FrozenInstanceError):
        status.running = True


async def test_disabled_services_start_no_worker_and_do_not_count_intentional_skip():
    service = SemanticProcessingService(
        RecordingRuntime(),
        config=SemanticProcessingConfig(enabled=False),
    )

    await service.start()

    assert service.submit(_message()) is False
    assert service.status().running is False
    assert service.status().dropped_count == 0


def test_two_applications_have_isolated_queues_and_counters():
    first = build_semantic_application(
        embedding_model=ConstantEmbeddingModel(),
        known_classes=(),
        decision_policy=_policy(),
    )
    second = build_semantic_application(
        embedding_model=ConstantEmbeddingModel(),
        known_classes=(),
        decision_policy=_policy(),
    )

    assert first.processing_service is not second.processing_service
    assert first.processing_service.status() == second.processing_service.status()
    assert first.processing_service.runtime is not second.processing_service.runtime
