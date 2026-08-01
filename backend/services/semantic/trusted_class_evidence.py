"""Trusted representation-specific prototype updates from confirmations."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from numbers import Real
from threading import RLock

from .candidate_confirmation import (
    CandidateConfirmation,
    CandidateConfirmationState,
)
from .stream_class import StreamClassEngine
from .unknown_stream_pool import UnknownStreamPool

_REPRESENTATION_NAMES = (
    "value_only",
    "key_only",
    "key_value",
    "schema",
    "numeric_key_only",
    "topic_key_value",
)


@dataclass(frozen=True, slots=True)
class RepresentationClassPrototype:
    """Trusted centroid evidence for one semantic class and representation."""

    semantic_class_name: str
    representation_name: str
    centroid: tuple[float, ...]
    member_count: int


@dataclass(frozen=True, slots=True)
class TrustedClassEvidence:
    """One representation-specific prototype with its unique accepted topics."""

    semantic_class_name: str
    representation_name: str
    centroid: tuple[float, ...]
    member_topics: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.semantic_class_name, str)
            or not self.semantic_class_name.strip()
        ):
            raise ValueError("semantic_class_name must be a non-empty string")
        if self.representation_name not in _REPRESENTATION_NAMES:
            raise ValueError(
                "representation_name must be one of the six representations"
            )
        centroid = TrustedClassEvidenceUpdater.validate_vector(
            self.centroid,
            self.representation_name,
            "trusted centroid",
        )
        try:
            topics = tuple(self.member_topics)
        except TypeError as exc:
            raise TypeError("member_topics must be an iterable of topics") from exc
        if not topics:
            raise ValueError("member_topics must not be empty")
        if any(not isinstance(topic, str) or not topic.strip() for topic in topics):
            raise ValueError("member_topics must contain non-empty strings")
        if len(set(topics)) != len(topics):
            raise ValueError("member_topics must not contain duplicates")
        object.__setattr__(self, "centroid", centroid)
        object.__setattr__(self, "member_topics", tuple(sorted(topics)))

    @property
    def member_count(self) -> int:
        """Return the number of unique trusted topics in this prototype."""
        return len(self.member_topics)

    @property
    def prototype(self) -> RepresentationClassPrototype:
        """Return the centroid-only view of this trusted evidence."""
        return RepresentationClassPrototype(
            semantic_class_name=self.semantic_class_name,
            representation_name=self.representation_name,
            centroid=self.centroid,
            member_count=self.member_count,
        )


class TrustedClassEvidenceStore:
    """In-memory store of latest trusted evidence per class and view."""

    def __init__(self, coordinator=None) -> None:
        self._evidence: dict[tuple[str, str], TrustedClassEvidence] = {}
        self._lock = RLock()
        self._coordinator = coordinator

    def get(
        self,
        semantic_class_name: str,
        representation_name: str,
    ) -> TrustedClassEvidence | None:
        """Return evidence for one semantic class and representation."""
        with self._lock:
            return self._evidence.get((semantic_class_name, representation_name))

    def upsert(self, evidence: TrustedClassEvidence) -> None:
        """Insert or replace representation-specific trusted evidence."""
        with self._lock:
            key = (evidence.semantic_class_name, evidence.representation_name)
            if self._evidence.get(key) == evidence:
                return
            self._evidence[key] = evidence
        if self._coordinator is not None:
            self._coordinator.mark_changed()

    def remove(
        self,
        semantic_class_name: str,
        representation_name: str,
    ) -> TrustedClassEvidence | None:
        """Remove and return one representation-specific evidence record."""
        with self._lock:
            removed = self._evidence.pop(
                (semantic_class_name, representation_name), None
            )
        if removed is not None and self._coordinator is not None:
            self._coordinator.mark_changed()
        return removed

    def all(self) -> tuple[TrustedClassEvidence, ...]:
        """Return evidence ordered by semantic class then representation."""
        with self._lock:
            return tuple(
                sorted(
                    self._evidence.values(),
                    key=lambda evidence: (
                        evidence.semantic_class_name,
                        evidence.representation_name,
                    ),
                )
            )

    def snapshot(self) -> tuple[TrustedClassEvidence, ...]:
        return self.all()

    def replace(self, evidence: tuple[TrustedClassEvidence, ...]) -> None:
        replacement = {
            (item.semantic_class_name, item.representation_name): item
            for item in evidence
        }
        if len(replacement) != len(evidence):
            raise ValueError("Trusted evidence snapshot contains duplicates")
        with self._lock:
            if self._evidence == replacement:
                return
            self._evidence = replacement
        if self._coordinator is not None:
            self._coordinator.mark_changed()

    def __len__(self) -> int:
        """Return the number of representation-specific evidence records."""
        with self._lock:
            return len(self._evidence)


class TrustedClassEvidenceUpdater:
    """Apply explicit confirmed feedback to one representation prototype."""

    def apply_confirmation(
        self,
        confirmation: CandidateConfirmation,
        unknown_pool: UnknownStreamPool,
        evidence_store: TrustedClassEvidenceStore,
    ) -> TrustedClassEvidence:
        """Create or update only the confirmation representation's prototype."""
        if confirmation.state is not CandidateConfirmationState.CONFIRMED:
            raise ValueError("Only CONFIRMED confirmations can update trusted evidence")

        semantic_class_name = confirmation.semantic_class_name
        representation_name = confirmation.identity.representation_name
        member_topics = confirmation.identity.member_topics
        entries = self._resolve_entries(member_topics, unknown_pool)
        vectors = tuple(
            self.validate_vector(
                getattr(entry.embeddings, representation_name),
                representation_name,
                entry.topic,
            )
            for entry in entries
        )

        existing = evidence_store.get(semantic_class_name, representation_name)
        new_topic_vectors = tuple(
            (topic, vector)
            for topic, vector in zip(member_topics, vectors, strict=True)
            if existing is None or topic not in existing.member_topics
        )
        if existing is not None and not new_topic_vectors:
            return existing

        if existing is None:
            try:
                centroid = StreamClassEngine.compute_centroid(
                    vector for _, vector in new_topic_vectors
                )
            except ValueError as exc:
                raise ValueError(
                    f"Invalid vector for representation '{representation_name}': {exc}"
                ) from exc
            evidence = TrustedClassEvidence(
                semantic_class_name=semantic_class_name,
                representation_name=representation_name,
                centroid=centroid,
                member_topics=tuple(topic for topic, _ in new_topic_vectors),
            )
        else:
            centroid = existing.centroid
            member_count = existing.member_count
            for _, vector in new_topic_vectors:
                try:
                    centroid = StreamClassEngine.update_centroid(
                        centroid,
                        member_count,
                        vector,
                    )
                except ValueError as exc:
                    raise ValueError(
                        f"Invalid vector for representation '{representation_name}': {exc}"
                    ) from exc
                member_count += 1
            evidence = TrustedClassEvidence(
                semantic_class_name=semantic_class_name,
                representation_name=representation_name,
                centroid=centroid,
                member_topics=existing.member_topics
                + tuple(topic for topic, _ in new_topic_vectors),
            )

        evidence_store.upsert(evidence)
        return evidence

    @staticmethod
    def _resolve_entries(
        member_topics: tuple[str, ...],
        unknown_pool: UnknownStreamPool,
    ) -> tuple:
        entries = tuple(unknown_pool.get(topic) for topic in member_topics)
        missing_topics = tuple(
            topic
            for topic, entry in zip(member_topics, entries, strict=True)
            if entry is None
        )
        if missing_topics:
            raise ValueError(
                "Missing UNKNOWN pool topics: " + ", ".join(missing_topics)
            )
        return entries

    @staticmethod
    def validate_vector(
        vector: Sequence[float],
        representation_name: str,
        topic: str,
    ) -> tuple[float, ...]:
        """Validate one trusted vector without normalizing or transforming it."""
        try:
            values = tuple(vector)
        except TypeError as exc:
            raise ValueError(
                f"Embedding for representation '{representation_name}', topic "
                f"'{topic}' must be an iterable vector"
            ) from exc
        if not values:
            raise ValueError(
                f"Embedding for representation '{representation_name}', topic "
                f"'{topic}' must not be empty"
            )
        for value in values:
            if isinstance(value, bool) or not isinstance(value, Real):
                raise TypeError(
                    f"Embedding for representation '{representation_name}', topic "
                    f"'{topic}' must contain real, finite values"
                )
            if not math.isfinite(value):
                raise ValueError(
                    f"Embedding for representation '{representation_name}', topic "
                    f"'{topic}' must contain real, finite values"
                )
        return tuple(float(value) for value in values)
