"""In-memory embedding of deterministic SmartMQTT stream representations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from services.embedding.base_model import BaseEmbeddingModel

from .representations import RepresentationBuilder, StreamRepresentations

_REPRESENTATION_NAMES = (
    "value_only",
    "key_only",
    "key_value",
    "schema",
    "numeric_key_only",
    "topic_key_value",
)


@dataclass(frozen=True, slots=True)
class RepresentationEmbeddings:
    """Immutable vectors matching every ``StreamRepresentations`` field."""

    value_only: tuple[float, ...]
    key_only: tuple[float, ...]
    key_value: tuple[float, ...]
    schema: tuple[float, ...]
    numeric_key_only: tuple[float, ...]
    topic_key_value: tuple[float, ...]

    def as_dict(self) -> dict[str, tuple[float, ...]]:
        """Return vectors keyed in deterministic representation order."""
        return {
            "value_only": self.value_only,
            "key_only": self.key_only,
            "key_value": self.key_value,
            "schema": self.schema,
            "numeric_key_only": self.numeric_key_only,
            "topic_key_value": self.topic_key_value,
        }


class RepresentationEmbedder:
    """Embed all deterministic stream representations in one model call."""

    def __init__(
        self,
        model: BaseEmbeddingModel,
        builder: RepresentationBuilder | None = None,
    ):
        self.model = model
        self.builder = builder if builder is not None else RepresentationBuilder()

    def embed(
        self,
        representations: StreamRepresentations,
    ) -> RepresentationEmbeddings:
        """Embed six representations as one batch and validate its shape."""
        texts = [
            representations.value_only,
            representations.key_only,
            representations.key_value,
            representations.schema,
            representations.numeric_key_only,
            representations.topic_key_value,
        ]
        vectors = list(self.model.encode(texts))

        expected_count = len(_REPRESENTATION_NAMES)
        if len(vectors) != expected_count:
            raise ValueError(
                "Embedding model returned "
                f"{len(vectors)} vectors; expected {expected_count}"
            )

        frozen_vectors: list[tuple[float, ...]] = []
        expected_dimension: int | None = None
        for name, vector in zip(_REPRESENTATION_NAMES, vectors, strict=True):
            try:
                frozen_vector = tuple(vector)
            except TypeError as exc:
                raise ValueError(
                    f"Embedding vector for '{name}' must be an iterable"
                ) from exc

            if not frozen_vector:
                raise ValueError(f"Embedding vector for '{name}' is empty")

            dimension = len(frozen_vector)
            if expected_dimension is None:
                expected_dimension = dimension
            elif dimension != expected_dimension:
                raise ValueError(
                    f"Embedding vector for '{name}' has dimension {dimension}; "
                    f"expected {expected_dimension}"
                )

            frozen_vectors.append(frozen_vector)

        return RepresentationEmbeddings(
            value_only=frozen_vectors[0],
            key_only=frozen_vectors[1],
            key_value=frozen_vectors[2],
            schema=frozen_vectors[3],
            numeric_key_only=frozen_vectors[4],
            topic_key_value=frozen_vectors[5],
        )

    def embed_stream(
        self,
        topic: str,
        tags: Mapping[Any, Any],
        fields: Mapping[Any, Any],
    ) -> RepresentationEmbeddings:
        """Build then embed all representations for one stream."""
        return self.embed(self.builder.build(topic, tags, fields))
