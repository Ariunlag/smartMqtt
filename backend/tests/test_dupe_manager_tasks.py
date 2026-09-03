import asyncio
import logging

import pytest

from services.dupe_manager import DupeManager


class FakeCanonicalizationService:
    pass


@pytest.mark.asyncio
async def test_duplicate_check_task_is_retained_until_completion():
    manager = DupeManager(store=object(), canonicalization_service=FakeCanonicalizationService())
    started = asyncio.Event()
    release = asyncio.Event()

    async def delayed_check(topic, embedding):
        started.set()
        await release.wait()

    manager._delayed_check = delayed_check

    await manager.check_new_topic("topic/a", [1.0, 0.0])
    await started.wait()

    assert len(manager._check_tasks) == 1
    task = next(iter(manager._check_tasks))
    assert task.get_name() == "duplicate-check:topic/a"

    release.set()
    await task
    await asyncio.sleep(0)

    assert manager._check_tasks == set()


@pytest.mark.asyncio
async def test_duplicate_check_exception_is_observed_and_logged(caplog):
    manager = DupeManager(store=object(), canonicalization_service=FakeCanonicalizationService())

    async def delayed_check(topic, embedding):
        raise RuntimeError("boom")

    manager._delayed_check = delayed_check

    with caplog.at_level(logging.ERROR):
        await manager.check_new_topic("topic/error", [1.0])
        task = next(iter(manager._check_tasks))
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.sleep(0)

    assert manager._check_tasks == set()
    assert "Delayed duplicate check failed" in caplog.text
    assert "boom" in caplog.text


@pytest.mark.asyncio
async def test_duplicate_manager_shutdown_cancels_pending_checks():
    manager = DupeManager(store=object(), canonicalization_service=FakeCanonicalizationService())
    started = asyncio.Event()

    async def delayed_check(topic, embedding):
        started.set()
        await asyncio.sleep(3600)

    manager._delayed_check = delayed_check

    await manager.check_new_topic("topic/slow", [1.0])
    await started.wait()
    task = next(iter(manager._check_tasks))

    await manager.shutdown()

    assert task.cancelled()
    assert manager._check_tasks == set()
