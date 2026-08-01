"""Representation-specific HDBSCAN discovery over UNKNOWN stream evidence."""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from numbers import Real

from sklearn.cluster import HDBSCAN

from .unknown_stream_pool import UnknownStreamEntry

_REPRESENTATION_NAMES = (
    "value_only",
    "key_only",
    "key_value",
    "schema",
    "numeric_key_only",
    "topic_key_value",
)


@dataclass(frozen=True, slots=True)
class HDBSCANDiscoveryConfig:
    """Explicit, evaluable configuration for UNKNOWN-stream clustering."""

    min_cluster_size: int
    min_samples: int | None = None
    cluster_selection_epsilon: float = 0.0
    cluster_selection_method: str = "eom"
    allow_single_cluster: bool = False
    metric: str = "euclidean"

    def __post_init__(self) -> None:
        self._validate_positive_int("min_cluster_size", self.min_cluster_size, 2)
        if self.min_samples is not None:
            self._validate_positive_int("min_samples", self.min_samples, 1)
        if isinstance(self.cluster_selection_epsilon, bool) or not isinstance(
            self.cluster_selection_epsilon, Real
        ):
            raise TypeError("cluster_selection_epsilon must be a real, finite value")
        if not math.isfinite(self.cluster_selection_epsilon):
            raise ValueError("cluster_selection_epsilon must be finite")
        if self.cluster_selection_epsilon < 0.0:
            raise ValueError("cluster_selection_epsilon must be at least 0")
        if self.cluster_selection_method not in {"eom", "leaf"}:
            raise ValueError("cluster_selection_method must be 'eom' or 'leaf'")
        if not isinstance(self.allow_single_cluster, bool):
            raise TypeError("allow_single_cluster must be a bool")
        if not isinstance(self.metric, str) or not self.metric.strip():
            raise ValueError("metric must be a non-empty string")

    @staticmethod
    def _validate_positive_int(name: str, value: int, minimum: int) -> None:
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"{name} must be an integer of at least {minimum}")
        if value < minimum:
            raise ValueError(f"{name} must be at least {minimum}")


@dataclass(frozen=True, slots=True)
class UnknownClusterCandidate:
    """Canonical candidate structure for one representation-specific cluster."""

    representation_name: str
    candidate_index: int
    member_topics: tuple[str, ...]

    @property
    def size(self) -> int:
        """Return the number of UNKNOWN streams in this candidate."""
        return len(self.member_topics)


@dataclass(frozen=True, slots=True)
class RepresentationDiscoveryResult:
    """Candidates and retained noise for one representation view."""

    representation_name: str
    candidates: tuple[UnknownClusterCandidate, ...]
    noise_topics: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class UnknownStreamDiscoveryResult:
    """Independent discovery results in the explicit six-view order."""

    representations: tuple[RepresentationDiscoveryResult, ...]

    def for_representation(self, name: str) -> RepresentationDiscoveryResult | None:
        """Return one view result, or ``None`` when the name is unknown."""
        return next(
            (
                result
                for result in self.representations
                if result.representation_name == name
            ),
            None,
        )


class UnknownStreamDiscoveryEngine:
    """Run HDBSCAN independently for every UNKNOWN stream representation."""

    def __init__(self, config: HDBSCANDiscoveryConfig):
        self.config = config

    def discover(
        self,
        entries: Iterable[UnknownStreamEntry],
    ) -> UnknownStreamDiscoveryResult:
        """Discover representation-specific candidate structure and noise."""
        ordered_entries = tuple(sorted(entries, key=lambda entry: entry.topic))
        self._validate_unique_topics(ordered_entries)
        topics = tuple(entry.topic for entry in ordered_entries)

        results = tuple(
            self._discover_representation(name, ordered_entries, topics)
            for name in _REPRESENTATION_NAMES
        )
        return UnknownStreamDiscoveryResult(representations=results)

    def _discover_representation(
        self,
        name: str,
        entries: tuple[UnknownStreamEntry, ...],
        topics: tuple[str, ...],
    ) -> RepresentationDiscoveryResult:
        vectors = tuple(
            self._validated_vector(getattr(entry.embeddings, name), name, entry.topic)
            for entry in entries
        )
        self._validate_dimensions(vectors, name)

        if len(entries) < self.config.min_cluster_size:
            return RepresentationDiscoveryResult(
                representation_name=name,
                candidates=(),
                noise_topics=topics,
            )

        labels = HDBSCAN(
            min_cluster_size=self.config.min_cluster_size,
            min_samples=self.config.min_samples,
            cluster_selection_epsilon=self.config.cluster_selection_epsilon,
            cluster_selection_method=self.config.cluster_selection_method,
            allow_single_cluster=self.config.allow_single_cluster,
            metric=self.config.metric,
        ).fit_predict(vectors)
        return self._result_from_labels(name, topics, labels)

    @staticmethod
    def _validated_vector(
        vector: Sequence[float],
        representation_name: str,
        topic: str,
    ) -> tuple[float, ...]:
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
        return values

    @staticmethod
    def _validate_dimensions(
        vectors: tuple[tuple[float, ...], ...],
        representation_name: str,
    ) -> None:
        if not vectors:
            return
        expected_dimension = len(vectors[0])
        for vector in vectors[1:]:
            if len(vector) != expected_dimension:
                raise ValueError(
                    f"Embedding dimension mismatch for representation "
                    f"'{representation_name}': expected {expected_dimension}, "
                    f"got {len(vector)}"
                )

    @staticmethod
    def _validate_unique_topics(entries: tuple[UnknownStreamEntry, ...]) -> None:
        seen: set[str] = set()
        for entry in entries:
            if entry.topic in seen:
                raise ValueError(f"Duplicate topic: '{entry.topic}'")
            seen.add(entry.topic)

    @staticmethod
    def _result_from_labels(
        representation_name: str,
        topics: tuple[str, ...],
        labels: Sequence[int],
    ) -> RepresentationDiscoveryResult:
        if len(labels) != len(topics):
            raise ValueError(
                "HDBSCAN returned a label count that does not match topics"
            )

        members_by_label: dict[int, list[str]] = {}
        noise_topics: list[str] = []
        for topic, raw_label in zip(topics, labels, strict=True):
            label = int(raw_label)
            if label == -1:
                noise_topics.append(topic)
            else:
                members_by_label.setdefault(label, []).append(topic)

        canonical_members = sorted(
            tuple(sorted(members)) for members in members_by_label.values()
        )
        candidates = tuple(
            UnknownClusterCandidate(
                representation_name=representation_name,
                candidate_index=index,
                member_topics=members,
            )
            for index, members in enumerate(canonical_members)
        )
        return RepresentationDiscoveryResult(
            representation_name=representation_name,
            candidates=candidates,
            noise_topics=tuple(sorted(noise_topics)),
        )
