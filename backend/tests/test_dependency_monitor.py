"""Tests for DependencyMonitor (issue #9 readiness + recovery)."""

import asyncio
import time

import pytest

from services.dependency_monitor import DependencyMonitor


class FakeService:
    def __init__(self, healthy=True, recover_after=None, check_delay=0.0):
        self._healthy = healthy
        self._recover_after = recover_after
        self._check_delay = check_delay
        self.connect_calls = 0

    def check_health(self):
        if self._check_delay:
            time.sleep(self._check_delay)
        return self._healthy

    def connect(self):
        self.connect_calls += 1
        if self._recover_after is not None and self.connect_calls >= self._recover_after:
            self._healthy = True


# Distinct class names so the snapshot keys don't collide.
class Postgres(FakeService):
    pass


class Qdrant(FakeService):
    pass


async def test_snapshot_reports_health_required_and_latency():
    mon = DependencyMonitor([Postgres(healthy=True), Qdrant(healthy=False)])
    snap = await mon.snapshot()
    assert snap["Postgres"]["healthy"] is True
    assert snap["Qdrant"]["healthy"] is False
    assert snap["Postgres"]["required"] is True
    assert "latency_ms" in snap["Postgres"]
    assert mon.is_ready(snap) is False  # a required dep is down


async def test_optional_dependency_does_not_block_readiness():
    pg, q = Postgres(healthy=True), Qdrant(healthy=False)
    mon = DependencyMonitor([pg, q], required=["Postgres"])
    snap = await mon.snapshot()
    assert mon.is_ready(snap) is True  # Qdrant not required


async def test_health_check_timeout_marks_unhealthy():
    slow = Postgres(healthy=True, check_delay=0.3)
    mon = DependencyMonitor([slow], timeout=0.05)
    snap = await mon.snapshot()
    assert snap["Postgres"]["healthy"] is False


async def test_connect_all_recovers_and_fires_on_recover():
    recovered = []
    svc = Postgres(healthy=False, recover_after=1)
    mon = DependencyMonitor([svc], on_recover=lambda name: recovered.append(name))
    await mon.connect_all()
    snap = await mon.snapshot()
    assert snap["Postgres"]["healthy"] is True
    assert svc.connect_calls == 1
    assert recovered == ["Postgres"]


async def test_background_loop_recovers_after_startup_degradation():
    # Starts down, becomes healthy on the 2nd connect attempt.
    svc = Postgres(healthy=False, recover_after=2)
    mon = DependencyMonitor([svc], base_delay=0.01, max_delay=0.05)
    await mon.start()
    try:
        # Poll until recovery or timeout.
        deadline = time.time() + 2.0
        ready = False
        while time.time() < deadline:
            snap = await mon.snapshot()
            if mon.is_ready(snap):
                ready = True
                break
            await asyncio.sleep(0.02)
        assert ready, "monitor did not recover the dependency in time"
    finally:
        await mon.stop()


async def test_on_recover_fires_only_on_transition():
    calls = []
    svc = Postgres(healthy=True)
    mon = DependencyMonitor([svc], on_recover=lambda name: calls.append(name))
    await mon.connect_all()  # first observation: down(default)->healthy transition
    await mon.connect_all()  # still healthy: no new transition
    assert calls == ["Postgres"]
