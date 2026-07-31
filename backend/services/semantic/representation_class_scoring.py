"""Independent known-class cosine evidence for six representation views."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from .representation_embedder import RepresentationEmbeddings
from .stream_class import StreamClassEngine


@dataclass(frozen=True, slots=True)
class RepresentationClassCentroids:
    """One known class with an independent centroid for every view."""

    class_id: str
    class_name: str
    centroids: RepresentationEmbeddings

    def __post_init__(self) -> None:
        if not isinstance(self.class_id, str) or not self.class_id.strip():
            raise ValueError("class_id must be a non-empty string")
        if not isinstance(self.class_name, str) or not self.class_name.strip():
            raise ValueError("class_name must be a non-empty string")


@dataclass(frozen=True, slots=True)
class RepresentationClassScores:
    """Six independent same-view cosine scores for one known class."""

    value_only: float
    key_only: float
    key_value: float
    schema: float
    numeric_key_only: float
    topic_key_value: float

    def as_dict(self) -> dict[str, float]:
        """Return scores in the explicit six-view contract order."""
        return {
            "value_only": self.value_only,
            "key_only": self.key_only,
            "key_value": self.key_value,
            "schema": self.schema,
            "numeric_key_only": self.numeric_key_only,
            "topic_key_value": self.topic_key_value,
        }


@dataclass(frozen=True, slots=True)
class RepresentationClassEvidence:
    """One known class's independent evidence across all six views."""

    class_id: str
    class_name: str
    scores: RepresentationClassScores


@dataclass(frozen=True, slots=True)
class RepresentationClassEvidenceMatrix:
    """Known-class evidence rows ordered deterministically by class ID."""

    rows: tuple[RepresentationClassEvidence, ...]

    def as_dict(self) -> dict[str, dict[str, object]]:
        """Return fresh serialization dictionaries without mutable internals."""
        return {
            row.class_id: {
                "class_name": row.class_name,
                "scores": row.scores.as_dict(),
            }
            for row in self.rows
        }


class RepresentationClassScorer:
    """Produce raw same-view cosine evidence without combining scores."""

    @classmethod
    def score(
        cls,
        stream_embeddings: RepresentationEmbeddings,
        classes: Iterable[RepresentationClassCentroids],
    ) -> RepresentationClassEvidenceMatrix:
        """Score every known class and sort evidence rows by class ID."""
        known_classes = tuple(classes)
        cls._validate_unique_ids(known_classes)
        ordered_classes = sorted(known_classes, key=lambda item: item.class_id)

        rows = tuple(
            RepresentationClassEvidence(
                class_id=known_class.class_id,
                class_name=known_class.class_name,
                scores=cls._score_class(stream_embeddings, known_class),
            )
            for known_class in ordered_classes
        )
        return RepresentationClassEvidenceMatrix(rows=rows)

    @classmethod
    def _score_class(
        cls,
        stream: RepresentationEmbeddings,
        known_class: RepresentationClassCentroids,
    ) -> RepresentationClassScores:
        centroids = known_class.centroids
        return RepresentationClassScores(
            value_only=cls._cosine(
                stream.value_only,
                centroids.value_only,
                known_class.class_id,
                "value_only",
            ),
            key_only=cls._cosine(
                stream.key_only,
                centroids.key_only,
                known_class.class_id,
                "key_only",
            ),
            key_value=cls._cosine(
                stream.key_value,
                centroids.key_value,
                known_class.class_id,
                "key_value",
            ),
            schema=cls._cosine(
                stream.schema,
                centroids.schema,
                known_class.class_id,
                "schema",
            ),
            numeric_key_only=cls._cosine(
                stream.numeric_key_only,
                centroids.numeric_key_only,
                known_class.class_id,
                "numeric_key_only",
            ),
            topic_key_value=cls._cosine(
                stream.topic_key_value,
                centroids.topic_key_value,
                known_class.class_id,
                "topic_key_value",
            ),
        )

    @staticmethod
    def _cosine(
        stream_vector: Sequence[float],
        class_centroid: Sequence[float],
        class_id: str,
        representation_name: str,
    ) -> float:
        try:
            return StreamClassEngine.cosine_similarity(
                stream_vector,
                class_centroid,
            )
        except ValueError as exc:
            raise ValueError(
                f"Invalid vector for class '{class_id}', "
                f"representation '{representation_name}': {exc}"
            ) from exc

    @staticmethod
    def _validate_unique_ids(
        classes: tuple[RepresentationClassCentroids, ...],
    ) -> None:
        seen = set()
        for known_class in classes:
            if known_class.class_id in seen:
                raise ValueError(f"Duplicate class_id: '{known_class.class_id}'")
            seen.add(known_class.class_id)
