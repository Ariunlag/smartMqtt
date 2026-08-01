"""In-memory retention of streams with UNKNOWN semantic decisions."""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock

from .representation_embedder import RepresentationEmbeddings
from .semantic_class_decision import (
    SemanticClassDecision,
    SemanticClassDecisionState,
)


@dataclass(frozen=True, slots=True)
class UnknownStreamEntry:
    """Latest six-view evidence for one stream retained in the UNKNOWN pool."""

    topic: str
    embeddings: RepresentationEmbeddings
    decision: SemanticClassDecision

    def __post_init__(self) -> None:
        if not isinstance(self.topic, str) or not self.topic.strip():
            raise ValueError("topic must be a non-empty string")
        if self.decision.state is not SemanticClassDecisionState.UNKNOWN:
            raise ValueError("UnknownStreamEntry requires an UNKNOWN decision")


@dataclass(frozen=True, slots=True)
class UnknownStreamPoolSnapshot:
    """One internally consistent immutable view of UNKNOWN pool contents."""

    version: int
    entries: tuple[UnknownStreamEntry, ...]


class UnknownStreamPool:
    """Store the latest immutable UNKNOWN evidence for each topic in memory."""

    def __init__(self, coordinator=None) -> None:
        self._entries: dict[str, UnknownStreamEntry] = {}
        self._version = 0
        self._lock = RLock()
        self._coordinator = coordinator

    def upsert(self, entry: UnknownStreamEntry) -> None:
        """Insert or replace the latest UNKNOWN evidence for an entry topic."""
        with self._lock:
            if self._entries.get(entry.topic) == entry:
                return
            self._entries[entry.topic] = entry
            self._version += 1
        if self._coordinator is not None:
            self._coordinator.mark_changed()

    def get(self, topic: str) -> UnknownStreamEntry | None:
        """Return one topic's retained UNKNOWN evidence, if present."""
        with self._lock:
            return self._entries.get(topic)

    def remove(self, topic: str) -> UnknownStreamEntry | None:
        """Remove and return an entry, or return ``None`` when it is absent."""
        with self._lock:
            removed = self._entries.pop(topic, None)
            if removed is not None:
                self._version += 1
        if removed is not None and self._coordinator is not None:
            self._coordinator.mark_changed()
        return removed

    def replace(self, entries: tuple[UnknownStreamEntry, ...], version: int) -> None:
        """Replace contents while preserving the exact persisted pool version."""
        if isinstance(version, bool) or not isinstance(version, int) or version < 0:
            raise ValueError("UNKNOWN pool version must be a non-negative integer")
        replacement = {entry.topic: entry for entry in entries}
        if len(replacement) != len(entries):
            raise ValueError("UNKNOWN pool snapshot contains duplicate topics")
        with self._lock:
            if self._entries == replacement and self._version == version:
                return
            self._entries = replacement
            self._version = version
        if self._coordinator is not None:
            self._coordinator.mark_changed()

    def all(self) -> tuple[UnknownStreamEntry, ...]:
        """Return all entries in deterministic ascending topic order."""
        return self.snapshot().entries

    def snapshot(self) -> UnknownStreamPoolSnapshot:
        """Return the current version and entries under one lock acquisition."""
        with self._lock:
            return UnknownStreamPoolSnapshot(
                version=self._version,
                entries=tuple(self._entries[topic] for topic in sorted(self._entries)),
            )

    @property
    def version(self) -> int:
        """Return the monotonic content version."""
        with self._lock:
            return self._version

    def __len__(self) -> int:
        """Return the number of unique topics retained in the pool."""
        with self._lock:
            return len(self._entries)
