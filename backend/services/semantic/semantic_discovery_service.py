"""Debounced, stale-safe UNKNOWN-stream discovery coordination."""

from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass
from numbers import Real
from threading import Lock

from .semantic_review_runtime import SemanticReviewRuntime
from .unknown_stream_discovery import UnknownStreamDiscoveryEngine
from .unknown_stream_pool import UnknownStreamPool, UnknownStreamPoolSnapshot

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SemanticDiscoveryConfig:
    """Operational scheduling configuration, not calibrated research values."""

    enabled: bool = True
    debounce_seconds: float = 1.0
    shutdown_timeout: float = 5.0

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise TypeError("enabled must be a bool")
        self._validate_duration("debounce_seconds", self.debounce_seconds)
        self._validate_duration("shutdown_timeout", self.shutdown_timeout)

    @staticmethod
    def _validate_duration(name: str, value: float) -> None:
        if isinstance(value, bool) or not isinstance(value, Real):
            raise TypeError(f"{name} must be a real, finite value")
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"{name} must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class SemanticDiscoveryStatus:
    """Immutable, vector-free discovery coordinator status."""

    running: bool
    enabled: bool
    request_pending: bool
    pool_version: int
    last_processed_version: int | None
    run_count: int
    published_count: int
    failed_count: int
    stale_discard_count: int
    candidate_count: int
    noise_topic_count: int
    last_error_message: str | None


class SemanticDiscoveryService:
    """Coordinate exactly one debounced discovery run at a time."""

    def __init__(
        self,
        unknown_pool: UnknownStreamPool,
        discovery_engine: UnknownStreamDiscoveryEngine,
        review_runtime: SemanticReviewRuntime,
        config: SemanticDiscoveryConfig | None = None,
    ) -> None:
        self.unknown_pool = unknown_pool
        self.discovery_engine = discovery_engine
        self.review_runtime = review_runtime
        self.config = config or SemanticDiscoveryConfig()
        self._coordinator: asyncio.Task[None] | None = None
        self._wake_event: asyncio.Event | None = None
        self._state_lock = Lock()
        self._accepting = False
        self._request_pending = False
        self._request_generation = 0
        self._active_run = False
        self._run_count = 0
        self._published_count = 0
        self._failed_count = 0
        self._stale_discard_count = 0
        self._last_processed_version: int | None = None
        self._candidate_count = 0
        self._noise_topic_count = 0
        self._last_error_message: str | None = None

    async def start(self) -> None:
        """Start one coordinator task; repeated starts are idempotent."""
        if not self.config.enabled or self._coordinator is not None:
            return
        self._wake_event = asyncio.Event()
        self._accepting = True
        self._coordinator = asyncio.create_task(
            self._coordinator_loop(),
            name="semantic-discovery-coordinator",
        )
        with self._state_lock:
            pending = self._request_pending
        if pending:
            self._wake_event.set()
        logger.info(
            "[semantic-discovery] started debounce_seconds=%.3f min_cluster_size=%d",
            self.config.debounce_seconds,
            self.discovery_engine.config.min_cluster_size,
        )

    def request(self) -> bool:
        """Coalesce a non-blocking discovery request without creating tasks."""
        return self._request(internal=False)

    async def stop(self) -> None:
        """Process final coalesced work within the shutdown bound, then stop."""
        coordinator = self._coordinator
        if coordinator is None:
            return
        self._accepting = False
        try:
            await asyncio.wait_for(
                self._wait_until_idle(),
                timeout=self.config.shutdown_timeout,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "[semantic-discovery] shutdown timed out after %.3f seconds",
                self.config.shutdown_timeout,
            )
        coordinator.cancel()
        await asyncio.gather(coordinator, return_exceptions=True)
        self._coordinator = None
        self._wake_event = None
        logger.info("[semantic-discovery] stopped")

    def status(self) -> SemanticDiscoveryStatus:
        """Return one immutable operational snapshot without vector data."""
        with self._state_lock:
            return SemanticDiscoveryStatus(
                running=(
                    self._coordinator is not None and not self._coordinator.done()
                ),
                enabled=self.config.enabled,
                request_pending=self._request_pending or self._active_run,
                pool_version=self.unknown_pool.version,
                last_processed_version=self._last_processed_version,
                run_count=self._run_count,
                published_count=self._published_count,
                failed_count=self._failed_count,
                stale_discard_count=self._stale_discard_count,
                candidate_count=self._candidate_count,
                noise_topic_count=self._noise_topic_count,
                last_error_message=self._last_error_message,
            )

    def _request(self, *, internal: bool) -> bool:
        if not self.config.enabled or (not internal and not self._accepting):
            return False
        with self._state_lock:
            already_pending = self._request_pending
            self._request_pending = True
            self._request_generation += 1
            wake_event = self._wake_event
        if wake_event is not None:
            wake_event.set()
        return not already_pending

    async def _coordinator_loop(self) -> None:
        wake_event = self._wake_event
        if wake_event is None:
            raise RuntimeError("Discovery wake event was not initialized")
        while True:
            await wake_event.wait()
            while True:
                wake_event.clear()
                with self._state_lock:
                    generation = self._request_generation
                await asyncio.sleep(self.config.debounce_seconds)
                with self._state_lock:
                    if generation != self._request_generation:
                        continue
                    self._request_pending = False
                    self._active_run = True
                break
            try:
                await self._run_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                with self._state_lock:
                    self._failed_count += 1
                    self._last_error_message = str(exc)
                logger.exception("[semantic-discovery] coordinator run failed")
            finally:
                with self._state_lock:
                    self._active_run = False

    async def _run_once(self) -> None:
        snapshot = self.unknown_pool.snapshot()
        with self._state_lock:
            self._run_count += 1
        if len(snapshot.entries) < self.discovery_engine.config.min_cluster_size:
            self._publish_below_minimum(snapshot)
            return

        try:
            result = await asyncio.to_thread(
                self.discovery_engine.discover,
                snapshot.entries,
            )
        except Exception as exc:
            with self._state_lock:
                self._failed_count += 1
                self._last_error_message = str(exc)
            logger.exception(
                "[semantic-discovery] failed pool_version=%d",
                snapshot.version,
            )
            return

        if self.unknown_pool.version != snapshot.version:
            with self._state_lock:
                self._stale_discard_count += 1
            self._request(internal=True)
            return

        self.review_runtime.replace_discovery(result)
        noise_topics = {
            topic
            for representation in result.representations
            for topic in representation.noise_topics
        }
        with self._state_lock:
            self._published_count += 1
            self._last_processed_version = snapshot.version
            self._candidate_count = len(self.review_runtime.list_candidates())
            self._noise_topic_count = len(noise_topics)
            self._last_error_message = None

    def _publish_below_minimum(self, snapshot: UnknownStreamPoolSnapshot) -> None:
        if self.unknown_pool.version != snapshot.version:
            with self._state_lock:
                self._stale_discard_count += 1
            self._request(internal=True)
            return
        self.review_runtime.clear_candidates()
        with self._state_lock:
            self._published_count += 1
            self._last_processed_version = snapshot.version
            self._candidate_count = 0
            self._noise_topic_count = len(snapshot.entries)
            self._last_error_message = None

    async def _wait_until_idle(self) -> None:
        while True:
            with self._state_lock:
                idle = not self._request_pending and not self._active_run
            if idle:
                return
            await asyncio.sleep(0.005)
