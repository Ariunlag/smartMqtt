"""Bounded topic-aware sidecar processing for recommendation evidence."""

from __future__ import annotations

import asyncio
import logging

from models.mqtt_message import MQTTMessage

logger = logging.getLogger(__name__)


class ClassRecommendationProcessingService:
    """Coalesce pending observations by topic without blocking MQTT/Influx."""

    def __init__(self, application, *, capacity: int = 1000) -> None:
        self.application = application
        self.capacity = capacity
        self._pending: dict[str, MQTTMessage] = {}
        self._queue: asyncio.Queue[str] | None = None
        self._worker: asyncio.Task | None = None
        self.running = False
        self.submitted = 0
        self.processed = 0
        self.failed = 0
        self.coalesced = 0
        self.dropped = 0

    async def start(self) -> None:
        if self.running:
            return
        self._queue = asyncio.Queue(maxsize=self.capacity)
        self.running = True
        self._worker = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self.running = False
        if self._worker is not None:
            self._worker.cancel()
            await asyncio.gather(self._worker, return_exceptions=True)
        self._worker = None
        self._queue = None

    def submit(self, message: MQTTMessage) -> bool:
        if not self.running or self._queue is None:
            self.dropped += 1
            return False
        self.submitted += 1
        if message.topic in self._pending:
            self._pending[message.topic] = message
            self.coalesced += 1
            return True
        try:
            self._queue.put_nowait(message.topic)
        except asyncio.QueueFull:
            self.dropped += 1
            logger.warning("Recommendation queue full; dropped topic=%s", message.topic)
            return False
        self._pending[message.topic] = message
        return True

    async def _run(self) -> None:
        assert self._queue is not None
        while True:
            topic = await self._queue.get()
            try:
                message = self._pending.pop(topic, None)
                if message is not None:
                    await self.application.observe(message)
                    self.processed += 1
            except asyncio.CancelledError:
                raise
            except Exception:
                self.failed += 1
                logger.exception("Recommendation processing failed for topic=%s", topic)
            finally:
                self._queue.task_done()

    def status(self) -> dict:
        return {
            "running": self.running,
            "queue_size": self._queue.qsize() if self._queue is not None else 0,
            "queue_capacity": self.capacity,
            "submitted": self.submitted,
            "processed": self.processed,
            "failed": self.failed,
            "coalesced": self.coalesced,
            "dropped": self.dropped,
        }
