"""In-memory retention of streams with UNKNOWN semantic decisions."""

from __future__ import annotations

from dataclasses import dataclass

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


class UnknownStreamPool:
    """Store the latest immutable UNKNOWN evidence for each topic in memory."""

    def __init__(self) -> None:
        self._entries: dict[str, UnknownStreamEntry] = {}

    def upsert(self, entry: UnknownStreamEntry) -> None:
        """Insert or replace the latest UNKNOWN evidence for an entry topic."""
        self._entries[entry.topic] = entry

    def get(self, topic: str) -> UnknownStreamEntry | None:
        """Return one topic's retained UNKNOWN evidence, if present."""
        return self._entries.get(topic)

    def remove(self, topic: str) -> UnknownStreamEntry | None:
        """Remove and return an entry, or return ``None`` when it is absent."""
        return self._entries.pop(topic, None)

    def all(self) -> tuple[UnknownStreamEntry, ...]:
        """Return all entries in deterministic ascending topic order."""
        return tuple(sorted(self._entries.values(), key=lambda entry: entry.topic))

    def __len__(self) -> int:
        """Return the number of unique topics retained in the pool."""
        return len(self._entries)
