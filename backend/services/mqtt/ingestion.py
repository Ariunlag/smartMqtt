"""Bounded MQTT ingestion queue with backpressure.

Sits between the (thread-based) Paho callback and the existing async handler
pipeline:

    Paho callback --submit_threadsafe--> bounded asyncio.Queue --> N workers --> process()

The Paho callback stays short (a single thread-safe hand-off) and never spawns
unbounded coroutines. Queue-full behavior is explicit and every drop is counted
and logged — messages are never silently discarded.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from models.mqtt_message import MQTTMessage

logger = logging.getLogger(__name__)

Processor = Callable[[MQTTMessage], Awaitable[None]]

_SHUTDOWN = object()


@dataclass
class IngestionMetrics:
    enqueued: int = 0
    processed: int = 0
    dropped: int = 0
    failed: int = 0
    retries: int = 0
    queue_full_events: int = 0

    def as_dict(self, queue_depth: int, maxsize: int) -> dict:
        return {
            **{f: getattr(self, f) for f in self.__dataclass_fields__},
            "queue_depth": queue_depth,
            "queue_maxsize": maxsize,
        }


class IngestionQueue:
    def __init__(
        self,
        process: Processor,
        *,
        maxsize: int = 1000,
        workers: int = 4,
        full_policy: str = "drop_new",
        max_retries: int = 0,
        retry_delay: float = 0.5,
        metrics_interval: float = 30.0,
        name: str = "mqtt",
    ):
        if full_policy not in {"drop_new", "drop_oldest"}:
            raise ValueError(f"unsupported full_policy: {full_policy}")
        self._process = process
        self._maxsize = maxsize
        self._worker_count = max(1, workers)
        self._full_policy = full_policy
        self._max_retries = max(0, max_retries)
        self._retry_delay = retry_delay
        self._metrics_interval = metrics_interval
        self._name = name

        self._queue: asyncio.Queue | None = None
        self._workers: list[asyncio.Task] = []
        self._metrics_task: asyncio.Task | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._accepting = False
        self.metrics = IngestionMetrics()

    # ---- lifecycle -------------------------------------------------------

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        """Create the queue and start workers. Must run on the event loop."""
        if self._workers:
            return
        self._loop = loop
        self._queue = asyncio.Queue(maxsize=self._maxsize)
        self._accepting = True
        self._workers = [
            loop.create_task(self._worker(i)) for i in range(self._worker_count)
        ]
        if self._metrics_interval > 0:
            self._metrics_task = loop.create_task(self._metrics_loop())
        logger.info(
            "[ingestion:%s] started maxsize=%d workers=%d policy=%s retries=%d",
            self._name,
            self._maxsize,
            self._worker_count,
            self._full_policy,
            self._max_retries,
        )

    async def stop(self, drain_timeout: float = 5.0) -> None:
        """Gracefully drain in-flight work, then stop workers."""
        if not self._workers or self._queue is None:
            return
        self._accepting = False
        if self._metrics_task is not None:
            self._metrics_task.cancel()
        timed_out = False
        try:
            await asyncio.wait_for(self._queue.join(), timeout=drain_timeout)
        except asyncio.TimeoutError:
            timed_out = True
            logger.warning(
                "[ingestion:%s] drain timed out; %d items still queued",
                self._name,
                self._queue.qsize(),
            )
        if timed_out:
            for worker in self._workers:
                worker.cancel()
            while True:
                try:
                    self._queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                else:
                    self._queue.task_done()
        else:
            for _ in self._workers:
                self._queue.put_nowait(_SHUTDOWN)
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        logger.info(
            "[ingestion:%s] stopped (processed=%d dropped=%d failed=%d)",
            self._name,
            self.metrics.processed,
            self.metrics.dropped,
            self.metrics.failed,
        )

    # ---- enqueue ---------------------------------------------------------

    def submit_threadsafe(self, message: MQTTMessage) -> None:
        """Hand a message from the Paho thread to the event loop (short)."""
        if self._loop is None or self._queue is None:
            logger.error("[ingestion:%s] not started; dropping message", self._name)
            self.metrics.dropped += 1
            return
        self._loop.call_soon_threadsafe(self.offer, message)

    def offer(self, message: MQTTMessage) -> bool:
        """Enqueue on the event loop, applying the full policy. Returns True if
        the message was accepted."""
        assert self._queue is not None
        if not self._accepting:
            self.metrics.dropped += 1
            logger.warning(
                "[ingestion:%s] stopped; dropped topic=%s (total_dropped=%d)",
                self._name,
                message.topic,
                self.metrics.dropped,
            )
            return False
        item = (message, time.monotonic())
        try:
            self._queue.put_nowait(item)
            self.metrics.enqueued += 1
            return True
        except asyncio.QueueFull:
            self.metrics.queue_full_events += 1
            if self._full_policy == "drop_oldest":
                try:
                    self._queue.get_nowait()
                    self._queue.task_done()
                    self.metrics.dropped += 1
                    self._queue.put_nowait(item)
                    self.metrics.enqueued += 1
                    logger.warning(
                        "[ingestion:%s] queue full; evicted oldest (depth=%d)",
                        self._name,
                        self._queue.qsize(),
                    )
                    return True
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    self.metrics.dropped += 1
                    return False
            # drop_new
            self.metrics.dropped += 1
            logger.warning(
                "[ingestion:%s] queue full (maxsize=%d); dropped topic=%s (total_dropped=%d)",
                self._name,
                self._maxsize,
                message.topic,
                self.metrics.dropped,
            )
            return False

    # ---- workers ---------------------------------------------------------

    async def _worker(self, wid: int) -> None:
        assert self._queue is not None
        q = self._queue
        while True:
            item = await q.get()
            try:
                if item is _SHUTDOWN:
                    return
                message, enqueued_at = item
                await self._handle_with_retries(message, enqueued_at)
            finally:
                q.task_done()

    async def _handle_with_retries(
        self, message: MQTTMessage, enqueued_at: float
    ) -> None:
        assert self._queue is not None
        for attempt in range(self._max_retries + 1):
            try:
                await self._process(message)
                self.metrics.processed += 1
                latency_ms = (time.monotonic() - enqueued_at) * 1000
                logger.debug(
                    "[ingestion:%s] processed topic=%s attempt=%d latency_ms=%.1f depth=%d",
                    self._name,
                    message.topic,
                    attempt,
                    latency_ms,
                    self._queue.qsize(),
                )
                return
            except Exception:
                if attempt < self._max_retries:
                    self.metrics.retries += 1
                    logger.warning(
                        "[ingestion:%s] processing failed topic=%s attempt=%d; retrying",
                        self._name,
                        message.topic,
                        attempt + 1,
                    )
                    await asyncio.sleep(self._retry_delay * (2**attempt))
                else:
                    self.metrics.failed += 1
                    logger.exception(
                        "[ingestion:%s] processing permanently failed topic=%s after %d attempt(s)",
                        self._name,
                        message.topic,
                        attempt + 1,
                    )

    async def _metrics_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(self._metrics_interval)
            except asyncio.CancelledError:
                return
            logger.info("[ingestion:%s] metrics %s", self._name, self.snapshot())

    # ---- introspection ---------------------------------------------------

    def snapshot(self) -> dict:
        depth = self._queue.qsize() if self._queue is not None else 0
        return self.metrics.as_dict(depth, self._maxsize)

    @property
    def queue_depth(self) -> int:
        return self._queue.qsize() if self._queue is not None else 0
