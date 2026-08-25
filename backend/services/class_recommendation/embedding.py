"""Batched dense embedding of independent pair representations."""

from __future__ import annotations

import math
from collections.abc import Sequence

from services.embedding.base_model import BaseEmbeddingModel

from .domain import PairEmbeddingRecord, PairRepresentation, PairView


class PairEmbeddingError(RuntimeError):
    """Pair embeddings could not be generated without a lexical fallback."""


class PairEmbedder:
    def __init__(self, model: BaseEmbeddingModel) -> None:
        self.model = model

    def embed(
        self, representations: Sequence[PairRepresentation]
    ) -> tuple[PairEmbeddingRecord, ...]:
        indexed: list[tuple[int, PairView]] = []
        texts: list[str] = []
        for index, pair in enumerate(representations):
            for view, value in pair.texts:
                indexed.append((index, view))
                texts.append(value)
        if not texts:
            return ()
        try:
            raw_vectors = self.model.encode(texts)
        except Exception as exc:
            raise PairEmbeddingError("Pair embedding model failed") from exc
        vectors = tuple(self._validate_vector(vector) for vector in raw_vectors)
        if len(vectors) != len(indexed):
            raise PairEmbeddingError(
                f"Embedding model returned {len(vectors)} vectors for {len(indexed)} texts"
            )
        dimensions = {len(vector) for vector in vectors}
        if len(dimensions) != 1:
            raise PairEmbeddingError("Embedding vectors have inconsistent dimensions")
        mapped: list[list[tuple[PairView, tuple[float, ...]]]] = [
            [] for _ in representations
        ]
        for (pair_index, view), vector in zip(indexed, vectors, strict=True):
            mapped[pair_index].append((view, vector))
        return tuple(
            PairEmbeddingRecord(pair, tuple(mapped[index]))
            for index, pair in enumerate(representations)
        )

    @staticmethod
    def _validate_vector(vector) -> tuple[float, ...]:
        try:
            result = tuple(float(value) for value in vector)
        except (TypeError, ValueError) as exc:
            raise PairEmbeddingError(
                "Embedding model returned a non-numeric vector"
            ) from exc
        if not result or not all(math.isfinite(value) for value in result):
            raise PairEmbeddingError(
                "Embedding model returned an empty or non-finite vector"
            )
        return result
