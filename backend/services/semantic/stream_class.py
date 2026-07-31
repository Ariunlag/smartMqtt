"""Dependency-free domain models and vector math for stream semantic classes."""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StreamClassMember:
    """One stream topic and its semantic vector."""

    topic: str
    vector: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class StreamSemanticClass:
    """A named stream class represented by an arithmetic-mean centroid."""

    class_id: str
    name: str
    centroid: tuple[float, ...]
    member_count: int


@dataclass(frozen=True, slots=True)
class ClassMatch:
    """Cosine-similarity result for one stream class."""

    class_id: str
    class_name: str
    similarity: float


class StreamClassEngine:
    """Compute centroids and rank semantic classes for one stream vector."""

    @classmethod
    def compute_centroid(
        cls,
        vectors: Iterable[Sequence[float]],
    ) -> tuple[float, ...]:
        """Return the unnormalized arithmetic mean of equal-size vectors."""
        frozen_vectors = tuple(
            cls._validated_vector(vector, f"vector {index}")
            for index, vector in enumerate(vectors)
        )
        if not frozen_vectors:
            raise ValueError("At least one vector is required")

        cls._validate_dimensions(frozen_vectors)
        count = len(frozen_vectors)
        return tuple(
            math.fsum(vector[index] for vector in frozen_vectors) / count
            for index in range(len(frozen_vectors[0]))
        )

    @classmethod
    def update_centroid(
        cls,
        old_centroid: Sequence[float],
        old_count: int,
        new_vector: Sequence[float],
    ) -> tuple[float, ...]:
        """Update an unnormalized arithmetic-mean centroid incrementally."""
        if (
            isinstance(old_count, bool)
            or not isinstance(old_count, int)
            or old_count < 1
        ):
            raise ValueError("old_count must be at least 1")

        centroid = cls._validated_vector(old_centroid, "old centroid")
        vector = cls._validated_vector(new_vector, "new vector")
        cls._validate_dimensions((centroid, vector))

        new_count = old_count + 1
        return tuple(
            (old_value * old_count + new_value) / new_count
            for old_value, new_value in zip(centroid, vector, strict=True)
        )

    @classmethod
    def cosine_similarity(
        cls,
        vector: Sequence[float],
        centroid: Sequence[float],
    ) -> float:
        """Score two vectors by cosine without modifying or normalizing them."""
        left = cls._validated_vector(vector, "stream vector")
        right = cls._validated_vector(centroid, "class centroid")
        cls._validate_dimensions((left, right))

        left_norm = math.sqrt(math.fsum(value * value for value in left))
        right_norm = math.sqrt(math.fsum(value * value for value in right))
        if left_norm == 0.0 or right_norm == 0.0:
            raise ValueError("Cosine similarity is undefined for zero-norm vectors")

        dot_product = math.fsum(
            left_value * right_value
            for left_value, right_value in zip(left, right, strict=True)
        )
        similarity = dot_product / (left_norm * right_norm)
        return max(-1.0, min(1.0, similarity))

    @classmethod
    def rank_classes(
        cls,
        vector: Sequence[float],
        classes: Iterable[StreamSemanticClass],
    ) -> tuple[ClassMatch, ...]:
        """Rank existing classes by similarity, then deterministically by ID."""
        stream_vector = cls._validated_vector(vector, "stream vector")
        matches = [
            ClassMatch(
                class_id=stream_class.class_id,
                class_name=stream_class.name,
                similarity=cls.cosine_similarity(
                    stream_vector,
                    stream_class.centroid,
                ),
            )
            for stream_class in classes
        ]
        matches.sort(key=lambda match: (-match.similarity, match.class_id))
        return tuple(matches)

    @staticmethod
    def _validated_vector(
        vector: Sequence[float],
        label: str,
    ) -> tuple[float, ...]:
        try:
            frozen = tuple(float(value) for value in vector)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label} must contain numeric values") from exc
        if not frozen:
            raise ValueError(f"{label} must not be empty")
        return frozen

    @staticmethod
    def _validate_dimensions(
        vectors: Sequence[Sequence[float]],
    ) -> None:
        expected = len(vectors[0])
        for index, vector in enumerate(vectors[1:], start=1):
            if len(vector) != expected:
                raise ValueError(
                    f"Vector dimension mismatch at index {index}: "
                    f"expected {expected}, got {len(vector)}"
                )
