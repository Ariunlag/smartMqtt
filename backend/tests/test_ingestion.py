"""Tests for the bounded MQTT ingestion queue (issue #1)."""

import asyncio

import pytest

from models.mqtt_message import MQTTMessage
from services.mqtt.ingestion import IngestionQueue


def make_message(topic="t/a"):
    return MQTTMessage(
        topic=topic,
        tags={"k": "v"},
        fields={"value": 1},
        timestamp="2024-01-01T00:00:00Z",
    )


async def test_processes_all_messages_within_capacity():
    seen = []
    q = IngestionQueue(
        lambda m: _collect(seen, m), maxsize=100, workers=4, metrics_interval=0
    )
    q.start(asyncio.get_running_loop())
    try:
        for i in range(50):
            assert q.offer(make_message(f"t/{i}")) is True
        await _drain(q)
        assert len(seen) == 50
        assert q.metrics.processed == 50
        assert q.metrics.dropped == 0
    finally:
        await q.stop()


async def _collect(sink, message):
    sink.append(message.topic)


async def _drain(q, timeout=2.0):
    await asyncio.wait_for(q._queue.join(), timeout=timeout)


async def test_drop_new_when_full_never_silent():
    # Block processing so the queue fills up, then over-offer.
    release = asyncio.Event()

    async def slow(_m):
        await release.wait()

    q = IngestionQueue(slow, maxsize=2, workers=1, full_policy="drop_new", metrics_interval=0)
    q.start(asyncio.get_running_loop())
    try:
        results = [q.offer(make_message(f"t/{i}")) for i in range(6)]
        # queue holds maxsize; one may be in-flight in the worker
        assert results.count(False) >= 3  # explicit drops
        assert q.metrics.dropped == results.count(False)
        assert q.metrics.queue_full_events >= 1
        assert q.queue_depth <= 2  # never exceeds maxsize
        release.set()
    finally:
        release.set()
        await q.stop()


async def test_drop_oldest_admits_newest():
    release = asyncio.Event()

    async def slow(_m):
        await release.wait()

    q = IngestionQueue(slow, maxsize=2, workers=1, full_policy="drop_oldest", metrics_interval=0)
    q.start(asyncio.get_running_loop())
    try:
        for i in range(5):
            q.offer(make_message(f"t/{i}"))
        assert q.metrics.dropped >= 1
        assert q.queue_depth <= 2
        release.set()
    finally:
        release.set()
        await q.stop()


async def test_burst_load_is_bounded_and_accounted():
    processed = []

    async def proc(m):
        await asyncio.sleep(0.001)
        processed.append(m.topic)

    q = IngestionQueue(proc, maxsize=10, workers=4, full_policy="drop_new", metrics_interval=0)
    q.start(asyncio.get_running_loop())
    try:
        max_depth = 0
        for i in range(500):  # burst well beyond capacity
            q.offer(make_message(f"t/{i}"))
            max_depth = max(max_depth, q.queue_depth)
        assert max_depth <= 10  # backpressure held the bound
        await _drain(q)
        # Every message is accounted for: processed + dropped == offered.
        assert q.metrics.processed + q.metrics.dropped == 500
        assert q.metrics.processed == len(processed)
    finally:
        await q.stop()


async def test_retries_then_succeeds():
    attempts = {"n": 0}

    async def flaky(_m):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise RuntimeError("transient")

    q = IngestionQueue(flaky, maxsize=10, workers=1, max_retries=3, retry_delay=0.0, metrics_interval=0)
    q.start(asyncio.get_running_loop())
    try:
        q.offer(make_message())
        await _drain(q)
        assert q.metrics.processed == 1
        assert q.metrics.retries == 2
        assert q.metrics.failed == 0
    finally:
        await q.stop()


async def test_permanent_failure_is_counted_not_raised():
    async def always_fail(_m):
        raise RuntimeError("boom")

    q = IngestionQueue(always_fail, maxsize=10, workers=1, max_retries=1, retry_delay=0.0, metrics_interval=0)
    q.start(asyncio.get_running_loop())
    try:
        q.offer(make_message())
        await _drain(q)
        assert q.metrics.failed == 1
        assert q.metrics.processed == 0
    finally:
        await q.stop()


async def test_graceful_shutdown_drains_inflight():
    processed = []

    async def proc(m):
        await asyncio.sleep(0.01)
        processed.append(m.topic)

    q = IngestionQueue(proc, maxsize=100, workers=4, metrics_interval=0)
    q.start(asyncio.get_running_loop())
    for i in range(20):
        q.offer(make_message(f"t/{i}"))
    await q.stop()  # should drain before stopping
    assert len(processed) == 20


async def test_snapshot_reports_depth_and_counters():
    q = IngestionQueue(lambda m: asyncio.sleep(0), maxsize=5, workers=1, metrics_interval=0)
    q.start(asyncio.get_running_loop())
    try:
        snap = q.snapshot()
        assert snap["queue_maxsize"] == 5
        assert "queue_depth" in snap
        assert set(["enqueued", "processed", "dropped", "failed", "retries", "queue_full_events"]).issubset(snap)
    finally:
        await q.stop()
