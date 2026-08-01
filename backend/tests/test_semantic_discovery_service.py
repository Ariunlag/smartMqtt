import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError

import pytest
from fastapi.testclient import TestClient
from main import create_app
from models.mqtt_message import MQTTMessage
from services.embedding.base_model import BaseEmbeddingModel
from services.semantic import (
    CandidateConfirmationSource,
    CandidateIdentity,
    CandidateMembershipReview,
    HDBSCANDiscoveryConfig,
    RepresentationDiscoveryResult,
    RepresentationEmbeddings,
    SemanticClassDecision,
    SemanticClassDecisionConfig,
    SemanticClassDecisionPolicy,
    SemanticClassDecisionReason,
    SemanticClassDecisionState,
    SemanticDiscoveryConfig,
    SemanticDiscoveryService,
    SemanticReviewRuntime,
    UnknownClusterCandidate,
    UnknownStreamDiscoveryResult,
    UnknownStreamEntry,
    UnknownStreamPool,
    build_semantic_application,
)

VIEWS = tuple(RepresentationEmbeddings.__dataclass_fields__)


class ConstantEmbeddingModel(BaseEmbeddingModel):
    def encode(self, texts):
        return [(1.0, 0.0) for _ in texts]


class ScriptedDiscoveryEngine:
    def __init__(self, actions=(), *, min_cluster_size=2, release=None):
        self.config = HDBSCANDiscoveryConfig(min_cluster_size=min_cluster_size)
        self.actions = list(actions)
        self.release = release
        self.calls = []
        self.thread_ids = []
        self.active = 0
        self.max_active = 0
        self._lock = threading.Lock()

    def discover(self, entries):
        frozen = tuple(entries)
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        self.calls.append(tuple(entry.topic for entry in frozen))
        self.thread_ids.append(threading.get_ident())
        try:
            if self.release is not None:
                self.release.wait(timeout=2)
            action = self.actions.pop(0) if self.actions else _result(frozen)
            if isinstance(action, Exception):
                raise action
            return action(frozen) if callable(action) else action
        finally:
            with self._lock:
                self.active -= 1


class TriggerRecorder:
    def __init__(self, pool):
        self.unknown_pool = pool
        self.calls = 0

    def request(self):
        self.calls += 1
        return True


class PoolMutatingRuntime:
    def __init__(self, pool):
        self.pool = pool

    def process(self, profile):
        if profile.topic == "unknown":
            self.pool.upsert(_entry("unknown"))
        elif profile.topic == "known":
            self.pool.remove("unknown")
        elif profile.topic == "failure":
            self.pool.upsert(_entry("failure"))
            raise RuntimeError("processing failed")


def _decision():
    return SemanticClassDecision(
        state=SemanticClassDecisionState.UNKNOWN,
        candidate=None,
        runner_up=None,
        similarity_margin=None,
        reasons=(SemanticClassDecisionReason.NO_KNOWN_CLASSES,),
    )


def _entry(topic, vector=(1.0, 0.0)):
    embeddings = RepresentationEmbeddings(**{name: vector for name in VIEWS})
    return UnknownStreamEntry(topic, embeddings, _decision())


def _result(entries, *, representation="schema", members=None, noise=()):
    topics = tuple(entry.topic for entry in entries)
    member_topics = tuple(members or topics)
    representations = []
    for name in VIEWS:
        candidates = (
            (UnknownClusterCandidate(name, 0, member_topics),)
            if name == representation and member_topics
            else ()
        )
        representations.append(
            RepresentationDiscoveryResult(
                representation_name=name,
                candidates=candidates,
                noise_topics=tuple(noise) if name == representation else topics,
            )
        )
    return UnknownStreamDiscoveryResult(tuple(representations))


def _message(topic):
    return MQTTMessage(
        topic=topic,
        tags={},
        fields={"reading": 1.0},
        timestamp="2024-01-01T00:00:00Z",
    )


def _policy():
    return SemanticClassDecisionPolicy(SemanticClassDecisionConfig(1, 0.8, 0.0, 0.2))


async def _wait_for(predicate, timeout=2.0):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.005)


def test_construction_starts_no_task_and_status_is_immutable():
    pool = UnknownStreamPool()
    service = SemanticDiscoveryService(
        pool,
        ScriptedDiscoveryEngine(),
        SemanticReviewRuntime(pool),
    )

    status = service.status()

    assert service._coordinator is None
    assert status.running is False
    assert status.pool_version == 0
    assert not hasattr(status, "embeddings")
    with pytest.raises(FrozenInstanceError):
        status.running = True


async def test_start_is_idempotent_and_requests_are_non_blocking_and_coalesced():
    pool = UnknownStreamPool()
    pool.upsert(_entry("A"))
    pool.upsert(_entry("B"))
    engine = ScriptedDiscoveryEngine()
    service = SemanticDiscoveryService(
        pool,
        engine,
        SemanticReviewRuntime(pool),
        SemanticDiscoveryConfig(debounce_seconds=0.02),
    )
    await service.start()
    coordinator = service._coordinator
    await service.start()

    started = time.perf_counter()
    accepted = [service.request() for _ in range(10)]
    elapsed = time.perf_counter() - started
    await _wait_for(lambda: service.status().published_count == 1)
    await service.stop()

    assert coordinator is not None
    assert accepted[0] is True
    assert accepted[1:] == [False] * 9
    assert elapsed < 0.05
    assert len(engine.calls) == 1


async def test_discovery_runs_off_loop_and_never_overlaps():
    pool = UnknownStreamPool()
    pool.upsert(_entry("A"))
    pool.upsert(_entry("B"))
    release = threading.Event()
    engine = ScriptedDiscoveryEngine(release=release)
    service = SemanticDiscoveryService(
        pool,
        engine,
        SemanticReviewRuntime(pool),
        SemanticDiscoveryConfig(debounce_seconds=0),
    )
    loop_thread = threading.get_ident()
    await service.start()
    service.request()
    await _wait_for(lambda: engine.active == 1)
    service.request()
    release.set()
    await _wait_for(lambda: service.status().run_count == 2)
    await service.stop()

    assert all(thread_id != loop_thread for thread_id in engine.thread_ids)
    assert engine.max_active == 1


async def test_below_minimum_atomically_clears_candidates_without_hdbscan():
    pool = UnknownStreamPool()
    pool.upsert(_entry("A"))
    review = SemanticReviewRuntime(pool)
    review.register_candidate(UnknownClusterCandidate("schema", 0, ("old", "set")))
    engine = ScriptedDiscoveryEngine(min_cluster_size=2)
    service = SemanticDiscoveryService(
        pool,
        engine,
        review,
        SemanticDiscoveryConfig(debounce_seconds=0),
    )
    await service.start()
    service.request()
    await _wait_for(lambda: service.status().published_count == 1)
    await service.stop()

    assert review.list_candidates() == ()
    assert engine.calls == []
    assert service.status().noise_topic_count == 1


async def test_valid_result_replaces_candidates_and_keeps_six_views_independent():
    pool = UnknownStreamPool()
    for topic in ("A", "B", "C"):
        pool.upsert(_entry(topic))
    result = UnknownStreamDiscoveryResult(
        tuple(
            RepresentationDiscoveryResult(
                name,
                (UnknownClusterCandidate(name, 0, ("A", "B")),),
                ("C",),
            )
            for name in VIEWS
        )
    )
    review = SemanticReviewRuntime(pool)
    service = SemanticDiscoveryService(
        pool,
        ScriptedDiscoveryEngine((result,)),
        review,
        SemanticDiscoveryConfig(debounce_seconds=0),
    )
    await service.start()
    service.request()
    await _wait_for(lambda: service.status().published_count == 1)
    await service.stop()

    candidates = review.list_candidates()
    assert tuple(item.identity.representation_name for item in candidates) == tuple(
        sorted(VIEWS)
    )
    assert all(item.identity.member_topics == ("A", "B") for item in candidates)
    assert all("C" not in item.identity.member_topics for item in candidates)
    assert service.status().candidate_count == 6
    assert service.status().noise_topic_count == 1


async def test_stale_result_is_discarded_and_fresh_run_is_published():
    pool = UnknownStreamPool()
    pool.upsert(_entry("A"))
    pool.upsert(_entry("B"))
    release = threading.Event()
    engine = ScriptedDiscoveryEngine(release=release)
    review = SemanticReviewRuntime(pool)
    service = SemanticDiscoveryService(
        pool,
        engine,
        review,
        SemanticDiscoveryConfig(debounce_seconds=0),
    )
    await service.start()
    service.request()
    await _wait_for(lambda: engine.active == 1)
    pool.upsert(_entry("C"))
    release.set()
    await _wait_for(lambda: service.status().published_count == 1)
    await service.stop()

    status = service.status()
    assert status.stale_discard_count == 1
    assert status.run_count == 2
    assert review.list_candidates()[0].identity.member_topics == ("A", "B", "C")


async def test_failure_preserves_candidates_and_later_request_succeeds():
    pool = UnknownStreamPool()
    pool.upsert(_entry("A"))
    pool.upsert(_entry("B"))
    old = UnknownClusterCandidate("schema", 0, ("old", "topics"))
    review = SemanticReviewRuntime(pool)
    review.register_candidate(old)
    engine = ScriptedDiscoveryEngine(
        (RuntimeError("HDBSCAN failed"), _result(pool.all()))
    )
    service = SemanticDiscoveryService(
        pool,
        engine,
        review,
        SemanticDiscoveryConfig(debounce_seconds=0),
    )
    await service.start()
    service.request()
    await _wait_for(lambda: service.status().failed_count == 1)
    assert review.list_candidates()[0].identity == CandidateIdentity.from_candidate(old)
    service.request()
    await _wait_for(lambda: service.status().published_count == 1)
    await service.stop()

    assert service.status().last_error_message is None
    assert review.list_candidates()[0].identity.member_topics == ("A", "B")


def test_successful_review_suppresses_exact_identity_but_failed_review_does_not():
    pool = UnknownStreamPool()
    for topic in ("A", "B", "C"):
        pool.upsert(_entry(topic))
    review = SemanticReviewRuntime(pool)
    exact = UnknownClusterCandidate("schema", 0, ("A", "B"))
    review.register_candidate(exact)
    successful = CandidateMembershipReview(
        identity=CandidateIdentity.from_candidate(exact),
        semantic_class_name="Temperature",
        kept_topics=("A", "B"),
        removed_topics=(),
        added_topics=(),
        source=CandidateConfirmationSource.HUMAN,
    )

    review.apply_review(successful)
    review.replace_discovery(_result(pool.all(), members=("A", "B")))
    assert review.list_candidates() == ()

    review.replace_discovery(_result(pool.all(), members=("A", "C")))
    different = review.list_candidates()[0]
    assert different.identity.member_topics == ("A", "C")
    failed = CandidateMembershipReview(
        identity=different.identity,
        semantic_class_name="Other",
        kept_topics=("A",),
        removed_topics=("C",),
        added_topics=("missing",),
        source=CandidateConfirmationSource.HUMAN,
    )
    with pytest.raises(ValueError, match="Missing final-member topic"):
        review.apply_review(failed)
    review.replace_discovery(_result(pool.all(), members=("A", "C")))
    assert review.list_candidates()[0].identity == different.identity


def test_concurrent_candidate_replacement_and_reads_observe_complete_sets():
    pool = UnknownStreamPool()
    review = SemanticReviewRuntime(pool)
    first = _result((), members=("A", "B"))
    second = UnknownStreamDiscoveryResult(
        (
            RepresentationDiscoveryResult(
                "schema",
                (
                    UnknownClusterCandidate("schema", 0, ("C", "D")),
                    UnknownClusterCandidate("schema", 1, ("E", "F")),
                ),
                (),
            ),
        )
    )
    review.replace_discovery(first)
    allowed = {
        (("schema", ("A", "B")),),
        (("schema", ("C", "D")), ("schema", ("E", "F"))),
    }

    def replace(index):
        review.replace_discovery(first if index % 2 == 0 else second)

    def read(_index):
        return tuple(
            (
                candidate.identity.representation_name,
                candidate.identity.member_topics,
            )
            for candidate in review.list_candidates()
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        replacements = [executor.submit(replace, index) for index in range(100)]
        reads = tuple(executor.map(read, range(100)))
        for future in replacements:
            future.result()

    assert set(reads) <= allowed


async def test_processing_requests_only_after_successful_pool_version_changes():
    pool = UnknownStreamPool()
    trigger = TriggerRecorder(pool)
    from services.semantic import SemanticProcessingConfig, SemanticProcessingService

    service = SemanticProcessingService(
        PoolMutatingRuntime(pool),
        config=SemanticProcessingConfig(),
        discovery_service=trigger,
    )
    await service.start()
    for topic in ("unknown", "unchanged", "known", "failure"):
        service.submit(_message(topic))
    await _wait_for(
        lambda: service.status().processed_count + service.status().failed_count == 4
    )
    await service.stop()

    assert trigger.calls == 2
    assert service.status().processed_count == 3
    assert service.status().failed_count == 1


def test_application_identity_is_exact_status_endpoint_uses_app_and_apps_isolate():
    first = build_semantic_application(
        embedding_model=ConstantEmbeddingModel(),
        known_classes=(),
        decision_policy=_policy(),
        discovery_config=SemanticDiscoveryConfig(debounce_seconds=0),
    )
    second = build_semantic_application(
        embedding_model=ConstantEmbeddingModel(),
        known_classes=(),
        decision_policy=_policy(),
    )

    assert first.discovery_service.unknown_pool is first.unknown_pool
    assert first.discovery_service.review_runtime is first.review_runtime
    assert first.processing_service.discovery_service is first.discovery_service
    assert first.discovery_engine is first.discovery_service.discovery_engine
    assert first.discovery_service is not second.discovery_service
    assert first.discovery_engine is not second.discovery_engine

    with TestClient(
        create_app(semantic_application=first, manage_services=False)
    ) as client:
        response = client.get("/api/semantic-review/discovery-status")

    assert response.status_code == 200
    assert response.json()["pool_version"] == 0
    assert "embedding" not in response.text.lower()
    assert "payload" not in response.text.lower()


def test_application_accepts_injected_discovery_service_as_shared_composition():
    source = build_semantic_application(
        embedding_model=ConstantEmbeddingModel(),
        known_classes=(),
        decision_policy=_policy(),
    )

    composed = build_semantic_application(
        embedding_model=ConstantEmbeddingModel(),
        known_classes=(),
        decision_policy=_policy(),
        discovery_service=source.discovery_service,
    )

    assert composed.discovery_service is source.discovery_service
    assert composed.discovery_engine is source.discovery_engine
    assert composed.review_runtime is source.review_runtime
    assert composed.unknown_pool is source.unknown_pool
    assert composed.processing_service.discovery_service is source.discovery_service


async def test_shutdown_timeout_is_bounded():
    pool = UnknownStreamPool()
    pool.upsert(_entry("A"))
    pool.upsert(_entry("B"))
    release = threading.Event()
    service = SemanticDiscoveryService(
        pool,
        ScriptedDiscoveryEngine(release=release),
        SemanticReviewRuntime(pool),
        SemanticDiscoveryConfig(debounce_seconds=0, shutdown_timeout=0.02),
    )
    await service.start()
    service.request()
    await _wait_for(lambda: service.discovery_engine.active == 1)
    started = time.perf_counter()
    await service.stop()
    elapsed = time.perf_counter() - started
    release.set()

    assert elapsed < 0.5
    assert service.status().running is False
