"""Bounded, debounced persistence lifecycle for semantic application state."""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from numbers import Real
from threading import Lock

from .semantic_persistence import (
    SemanticPersistenceCompatibilityError,
    SemanticPersistenceRecord,
    SemanticSnapshotSerializer,
    SemanticStateRepository,
)
from .semantic_state import (
    SEMANTIC_STATE_SCHEMA_VERSION,
    SemanticApplicationSnapshot,
    SemanticStateCoordinator,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SemanticPersistenceConfig:
    enabled: bool = True
    state_key: str = "default"
    save_debounce_seconds: float = 1.0
    save_timeout: float = 5.0
    restore_timeout: float = 5.0
    shutdown_flush_timeout: float = 5.0
    require_compatible_restore: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise TypeError("enabled must be a bool")
        if not isinstance(self.state_key, str) or not self.state_key.strip():
            raise ValueError("state_key must be a non-empty string")
        if not isinstance(self.require_compatible_restore, bool):
            raise TypeError("require_compatible_restore must be a bool")
        for name in (
            "save_debounce_seconds",
            "save_timeout",
            "restore_timeout",
            "shutdown_flush_timeout",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, Real):
                raise TypeError(f"{name} must be numeric and finite")
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class SemanticPersistenceStatus:
    """Immutable, vector-free operational persistence status."""

    enabled: bool
    running: bool
    restored: bool
    degraded: bool
    schema_version: int
    current_generation: int
    persisted_generation: int | None
    save_pending: bool
    save_count: int
    restore_count: int
    failed_save_count: int
    failed_restore_count: int
    last_saved_at: datetime | None
    last_restored_at: datetime | None
    last_error_message: str | None
    compatibility_error: str | None


class SemanticPersistenceService:
    """Capture consistent snapshots and write them with one async coordinator."""

    def __init__(
        self,
        *,
        repository: SemanticStateRepository,
        coordinator: SemanticStateCoordinator,
        snapshot_provider: Callable[[], SemanticApplicationSnapshot],
        restore_handler: Callable[[SemanticApplicationSnapshot], None],
        model_fingerprint: str,
        representation_contract_version: str,
        config: SemanticPersistenceConfig | None = None,
        serializer: SemanticSnapshotSerializer | None = None,
    ) -> None:
        self.repository = repository
        self.coordinator = coordinator
        self.snapshot_provider = snapshot_provider
        self.restore_handler = restore_handler
        self.model_fingerprint = model_fingerprint
        self.representation_contract_version = representation_contract_version
        self.config = config or SemanticPersistenceConfig()
        self.serializer = serializer or SemanticSnapshotSerializer()
        self._writer: asyncio.Task[None] | None = None
        self._wake_event: asyncio.Event | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._status_lock = Lock()
        self._repository_save_lock = Lock()
        self._accepting = False
        self._dirty_generation: int | None = None
        self._active_save = False
        self._save_count = 0
        self._restore_count = 0
        self._failed_save_count = 0
        self._failed_restore_count = 0
        self._persisted_generation: int | None = None
        self._restore_attempted = False
        self._restored = False
        self._degraded = False
        self._last_saved_at: datetime | None = None
        self._last_restored_at: datetime | None = None
        self._last_error_message: str | None = None
        self._compatibility_error: str | None = None
        coordinator.add_listener(self._on_generation)

    async def restore(self) -> bool:
        """Load and atomically restore state before any semantic workers start."""
        if not self.config.enabled:
            return False
        with self._status_lock:
            if self._restore_attempted:
                return self._restored
            self._restore_attempted = True
        try:
            record = await asyncio.wait_for(
                asyncio.to_thread(self.repository.load, self.config.state_key),
                timeout=self.config.restore_timeout,
            )
            if record is None:
                with self._status_lock:
                    self._restore_count += 1
                    self._last_restored_at = datetime.now(timezone.utc)
                    self._last_error_message = None
                return False
            snapshot = self.serializer.deserialize(
                record,
                expected_model_fingerprint=self.model_fingerprint,
                expected_representation_contract_version=(
                    self.representation_contract_version
                ),
            )
            self.restore_handler(snapshot)
        except Exception as exc:
            compatibility = (
                str(exc)
                if isinstance(exc, SemanticPersistenceCompatibilityError)
                else None
            )
            with self._status_lock:
                self._degraded = True
                self._failed_restore_count += 1
                self._last_error_message = str(exc)
                self._compatibility_error = compatibility
            if self.config.require_compatible_restore:
                raise
            logger.warning(
                "[semantic-persistence] restore unavailable state_key=%s error=%s",
                self.config.state_key,
                type(exc).__name__,
            )
            return False
        with self._status_lock:
            self._restored = True
            self._degraded = False
            self._restore_count += 1
            self._persisted_generation = snapshot.generation
            self._last_restored_at = datetime.now(timezone.utc)
            self._last_error_message = None
            self._compatibility_error = None
        return True

    async def start(self) -> None:
        """Start exactly one writer task; repeated starts are idempotent."""
        if not self.config.enabled or self._writer is not None:
            return
        self._loop = asyncio.get_running_loop()
        self._wake_event = asyncio.Event()
        self._accepting = True
        self._writer = asyncio.create_task(
            self._writer_loop(), name="semantic-persistence-writer"
        )
        with self._status_lock:
            pending = self._dirty_generation is not None
        if pending:
            self._wake_event.set()

    def request_save(self, generation: int | None = None) -> bool:
        """Coalesce one non-blocking, thread-safe save request."""
        if not self.config.enabled:
            return False
        requested = self.coordinator.generation if generation is None else generation
        with self._status_lock:
            already_pending = self._dirty_generation is not None
            if self._dirty_generation is None or requested > self._dirty_generation:
                self._dirty_generation = requested
            loop = self._loop
            event = self._wake_event
        if loop is not None and event is not None and not loop.is_closed():
            loop.call_soon_threadsafe(event.set)
        return not already_pending

    async def flush(self) -> bool:
        """Wait within the save bound until the latest dirty generation is stored."""
        if not self.config.enabled:
            return True
        self.request_save()
        try:
            await asyncio.wait_for(
                self._wait_until_clean(), timeout=self.config.save_timeout
            )
            return True
        except asyncio.TimeoutError:
            return False

    async def stop(self) -> None:
        """Bound the final flush and stop the sole persistence writer."""
        writer = self._writer
        if writer is None:
            return
        self._accepting = False
        self.request_save()
        try:
            await asyncio.wait_for(
                self._wait_until_clean(),
                timeout=self.config.shutdown_flush_timeout,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "[semantic-persistence] shutdown flush timed out state_key=%s",
                self.config.state_key,
            )
        writer.cancel()
        await asyncio.gather(writer, return_exceptions=True)
        self._writer = None
        self._wake_event = None
        self._loop = None

    def status(self) -> SemanticPersistenceStatus:
        with self._status_lock:
            return SemanticPersistenceStatus(
                enabled=self.config.enabled,
                running=self._writer is not None and not self._writer.done(),
                restored=self._restored,
                degraded=self._degraded,
                schema_version=SEMANTIC_STATE_SCHEMA_VERSION,
                current_generation=self.coordinator.generation,
                persisted_generation=self._persisted_generation,
                save_pending=self._dirty_generation is not None or self._active_save,
                save_count=self._save_count,
                restore_count=self._restore_count,
                failed_save_count=self._failed_save_count,
                failed_restore_count=self._failed_restore_count,
                last_saved_at=self._last_saved_at,
                last_restored_at=self._last_restored_at,
                last_error_message=self._last_error_message,
                compatibility_error=self._compatibility_error,
            )

    def _on_generation(self, generation: int) -> None:
        self.request_save(generation)

    async def _writer_loop(self) -> None:
        event = self._wake_event
        if event is None:
            raise RuntimeError("Persistence wake event was not initialized")
        while True:
            await event.wait()
            event.clear()
            await asyncio.sleep(self.config.save_debounce_seconds)
            with self._status_lock:
                target = self._dirty_generation
                self._active_save = target is not None
            if target is None:
                continue
            failed = False
            try:
                snapshot = self.snapshot_provider()
                record = self.serializer.serialize(snapshot, self.config.state_key)
                saved = await asyncio.wait_for(
                    asyncio.to_thread(self._save_record, record),
                    timeout=self.config.save_timeout,
                )
                if not saved:
                    raise RuntimeError("Repository rejected stale semantic generation")
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - writer must survive repository errors
                failed = True
                with self._status_lock:
                    self._failed_save_count += 1
                    self._degraded = True
                    self._last_error_message = str(exc)
                logger.warning(
                    "[semantic-persistence] save failed state_key=%s generation=%s error=%s",
                    self.config.state_key,
                    target,
                    type(exc).__name__,
                )
            else:
                with self._status_lock:
                    self._save_count += 1
                    self._persisted_generation = record.generation
                    if (
                        self._dirty_generation is not None
                        and self._dirty_generation <= record.generation
                    ):
                        self._dirty_generation = None
                    self._degraded = False
                    self._last_saved_at = datetime.now(timezone.utc)
                    self._last_error_message = None
            finally:
                with self._status_lock:
                    self._active_save = False
                    more = (
                        self._dirty_generation is not None
                        and self._dirty_generation > (self._persisted_generation or -1)
                    )
                if more and self._accepting and not failed:
                    event.set()

    async def _wait_until_clean(self) -> None:
        while True:
            with self._status_lock:
                clean = self._dirty_generation is None and not self._active_save
            if clean:
                return
            await asyncio.sleep(0.005)

    def _save_record(self, record: SemanticPersistenceRecord) -> bool:
        """Prevent timed-out worker threads from overlapping repository writes."""
        with self._repository_save_lock:
            return self.repository.save(record)
