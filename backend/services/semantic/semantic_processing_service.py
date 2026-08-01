"""Bounded asynchronous sidecar for live semantic MQTT processing."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from numbers import Real
from threading import Lock

from models.mqtt_message import MQTTMessage

from .semantic_runtime import SemanticRuntimeOrchestrator
from .stream_profiler import StreamProfiler

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SemanticProcessingConfig:
    """Explicit lifecycle and backpressure settings for semantic processing."""

    enabled: bool = True
    queue_max_size: int = 256
    shutdown_drain_timeout: float = 5.0

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise TypeError("enabled must be a bool")
        if isinstance(self.queue_max_size, bool) or not isinstance(
            self.queue_max_size, int
        ):
            raise TypeError("queue_max_size must be an integer")
        if self.queue_max_size <= 0:
            raise ValueError("queue_max_size must be a positive integer")
        if isinstance(self.shutdown_drain_timeout, bool) or not isinstance(
            self.shutdown_drain_timeout, Real
        ):
            raise TypeError("shutdown_drain_timeout must be numeric")
        if self.shutdown_drain_timeout < 0:
            raise ValueError("shutdown_drain_timeout must be non-negative")


@dataclass(frozen=True, slots=True)
class SemanticProcessingStatus:
    """Immutable, payload-free snapshot of semantic sidecar operation."""

    running: bool
    enabled: bool
    queue_size: int
    queue_capacity: int
    submitted_count: int
    processed_count: int
    failed_count: int
    dropped_count: int
    last_processed_topic: str | None
    last_error_topic: str | None
    last_error_message: str | None


class SemanticProcessingService:
    """Process MQTT observations through one ordered semantic worker."""

    def __init__(
        self,
        runtime: SemanticRuntimeOrchestrator,
        profile_builder: StreamProfiler | None = None,
        config: SemanticProcessingConfig | None = None,
    ) -> None:
        self.runtime = runtime
        self.profile_builder = profile_builder or StreamProfiler()
        self.config = config or SemanticProcessingConfig()
        self._queue: asyncio.Queue[MQTTMessage] | None = None
        self._worker: asyncio.Task[None] | None = None
        self._accepting = False
        self._status_lock = Lock()
        self._submitted_count = 0
        self._processed_count = 0
        self._failed_count = 0
        self._dropped_count = 0
        self._last_processed_topic: str | None = None
        self._last_error_topic: str | None = None
        self._last_error_message: str | None = None

    async def start(self) -> None:
        """Start exactly one FIFO worker; repeated starts are idempotent."""
        if not self.config.enabled or self._worker is not None:
            return
        self._queue = asyncio.Queue(maxsize=self.config.queue_max_size)
        self._accepting = True
        self._worker = asyncio.create_task(
            self._worker_loop(),
            name="semantic-processing-worker",
        )
        logger.info(
            "[semantic-processing] started queue_capacity=%d workers=1",
            self.config.queue_max_size,
        )

    def submit(self, message: MQTTMessage) -> bool:
        """Offer one message without awaiting semantic processing."""
        if not isinstance(message, MQTTMessage):
            raise TypeError("message must be an MQTTMessage")
        if not self.config.enabled:
            return False
        queue = self._queue
        if not self._accepting or queue is None:
            self._record_drop()
            logger.warning(
                "[semantic-processing] unavailable; dropped topic=%s",
                message.topic,
            )
            return False
        try:
            queue.put_nowait(message)
        except asyncio.QueueFull:
            self._record_drop()
            logger.warning(
                "[semantic-processing] queue full; dropped topic=%s capacity=%d",
                message.topic,
                self.config.queue_max_size,
            )
            return False
        with self._status_lock:
            self._submitted_count += 1
        return True

    async def stop(self) -> None:
        """Stop accepting, drain within the configured bound, then stop."""
        worker = self._worker
        queue = self._queue
        if worker is None or queue is None:
            return
        self._accepting = False
        try:
            await asyncio.wait_for(
                queue.join(),
                timeout=self.config.shutdown_drain_timeout,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "[semantic-processing] drain timed out queue_size=%d timeout=%.3f",
                queue.qsize(),
                self.config.shutdown_drain_timeout,
            )
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)
        discarded = self._discard_queued(queue)
        if discarded:
            with self._status_lock:
                self._dropped_count += discarded
        self._worker = None
        self._queue = None
        logger.info("[semantic-processing] stopped")

    def status(self) -> SemanticProcessingStatus:
        """Return a deterministic immutable operational snapshot."""
        queue = self._queue
        with self._status_lock:
            return SemanticProcessingStatus(
                running=self._worker is not None and not self._worker.done(),
                enabled=self.config.enabled,
                queue_size=queue.qsize() if queue is not None else 0,
                queue_capacity=self.config.queue_max_size,
                submitted_count=self._submitted_count,
                processed_count=self._processed_count,
                failed_count=self._failed_count,
                dropped_count=self._dropped_count,
                last_processed_topic=self._last_processed_topic,
                last_error_topic=self._last_error_topic,
                last_error_message=self._last_error_message,
            )

    async def _worker_loop(self) -> None:
        queue = self._queue
        if queue is None:
            raise RuntimeError("Semantic processing queue was not initialized")
        while True:
            message = await queue.get()
            try:
                profile = self.profile_builder.profile(
                    message.topic,
                    message.tags,
                    message.fields,
                )
                await asyncio.to_thread(self.runtime.process, profile)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                with self._status_lock:
                    self._failed_count += 1
                    self._last_error_topic = message.topic
                    self._last_error_message = str(exc)
                logger.exception(
                    "[semantic-processing] failed topic=%s",
                    message.topic,
                )
            else:
                with self._status_lock:
                    self._processed_count += 1
                    self._last_processed_topic = message.topic
            finally:
                queue.task_done()

    def _record_drop(self) -> None:
        with self._status_lock:
            self._dropped_count += 1

    @staticmethod
    def _discard_queued(queue: asyncio.Queue[MQTTMessage]) -> int:
        discarded = 0
        while True:
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                return discarded
            else:
                discarded += 1
                queue.task_done()
