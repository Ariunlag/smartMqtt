"""Dependency health monitoring and background recovery.

Dependency-injected and free of concrete client imports so it can be unit
tested with fakes. Health checks are synchronous/blocking on the underlying
clients, so they are run off the event loop via ``asyncio.to_thread`` and
bounded with an explicit timeout.
"""

import asyncio
import logging
from typing import Any, Callable, Iterable, Optional

logger = logging.getLogger(__name__)

# A dependency is any object exposing a synchronous ``check_health() -> bool``
# and, optionally, ``connect()``.
Dependency = Any
RecoverCallback = Callable[[str], Any]


class DependencyMonitor:
    def __init__(
        self,
        services: Iterable[Dependency],
        *,
        timeout: float = 2.0,
        base_delay: float = 2.0,
        max_delay: float = 30.0,
        required: Optional[Iterable[str]] = None,
        on_recover: Optional[RecoverCallback] = None,
    ):
        self._services = list(services)
        self._timeout = timeout
        self._base_delay = base_delay
        self._max_delay = max_delay
        self._required = (
            set(required)
            if required is not None
            else {self._name(s) for s in self._services}
        )
        self._on_recover = on_recover
        self._task: Optional[asyncio.Task] = None
        self._stopping = False
        self._healthy: dict[str, bool] = {}

    @staticmethod
    def _name(svc: Dependency) -> str:
        return svc.__class__.__name__

    async def _check(self, svc: Dependency) -> bool:
        if not hasattr(svc, "check_health"):
            return True
        try:
            return bool(
                await asyncio.wait_for(
                    asyncio.to_thread(svc.check_health), self._timeout
                )
            )
        except asyncio.TimeoutError:
            logger.warning("health check timed out: %s", self._name(svc))
            return False
        except Exception:
            logger.exception("health check error: %s", self._name(svc))
            return False

    async def snapshot(self) -> dict[str, dict]:
        """Return per-dependency health, required flag, and check latency."""
        result: dict[str, dict] = {}
        loop = asyncio.get_running_loop()
        for svc in self._services:
            start = loop.time()
            healthy = await self._check(svc)
            result[self._name(svc)] = {
                "healthy": healthy,
                "required": self._name(svc) in self._required,
                "latency_ms": round((loop.time() - start) * 1000, 1),
            }
        return result

    def is_ready(self, snapshot: dict[str, dict]) -> bool:
        return all(
            info["healthy"] for info in snapshot.values() if info["required"]
        )

    async def _ensure(self, svc: Dependency) -> bool:
        """Check a dependency; reconnect if down; fire on_recover on transition."""
        healthy = await self._check(svc)
        if not healthy and hasattr(svc, "connect"):
            logger.info("recovery: reconnecting %s", self._name(svc))
            try:
                await asyncio.to_thread(svc.connect)
            except Exception:
                logger.exception("recovery connect failed: %s", self._name(svc))
            healthy = await self._check(svc)

        name = self._name(svc)
        was_healthy = self._healthy.get(name, False)
        self._healthy[name] = healthy
        if healthy and not was_healthy and self._on_recover is not None:
            await self._fire_recover(name)
        return healthy

    async def _fire_recover(self, name: str) -> None:
        try:
            result = self._on_recover(name)  # type: ignore[misc]
            if asyncio.iscoroutine(result):
                await result
        except Exception:
            logger.exception("on_recover callback failed: %s", name)

    async def connect_all(self) -> None:
        for svc in self._services:
            await self._ensure(svc)

    async def start(self) -> None:
        """Attempt an initial connect, then run background recovery."""
        self._stopping = False
        await self.connect_all()
        self._task = asyncio.create_task(self._loop())

    async def _loop(self) -> None:
        delay = self._base_delay
        while not self._stopping:
            try:
                await asyncio.sleep(delay)
            except asyncio.CancelledError:
                break
            all_healthy = True
            for svc in self._services:
                ok = await self._ensure(svc)
                all_healthy = all_healthy and ok
            delay = self._base_delay if all_healthy else min(self._max_delay, delay * 2)

    async def stop(self) -> None:
        self._stopping = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
