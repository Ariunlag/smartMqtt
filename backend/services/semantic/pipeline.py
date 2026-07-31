"""Orchestration for building, embedding, and storing stream representations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .representation_embedder import RepresentationEmbedder, RepresentationEmbeddings
from .representations import RepresentationBuilder, StreamRepresentations

if TYPE_CHECKING:
    from services.store.representation_embedding_store import (
        RepresentationEmbeddingStore,
    )


@dataclass(frozen=True, slots=True)
class StreamSemanticPipelineResult:
    """Representations and embeddings produced for one stream."""

    representations: StreamRepresentations
    embeddings: RepresentationEmbeddings


class StreamSemanticPipeline:
    """Coordinate deterministic representation, embedding, and storage stages."""

    def __init__(
        self,
        builder: RepresentationBuilder,
        embedder: RepresentationEmbedder,
        store: RepresentationEmbeddingStore,
    ):
        self.builder = builder
        self.embedder = embedder
        self.store = store

    def process(
        self,
        topic: str,
        tags: Mapping[Any, Any],
        fields: Mapping[Any, Any],
    ) -> StreamSemanticPipelineResult:
        """Build, embed, and store one stream's representations."""
        representations = self.builder.build(topic, tags, fields)
        embeddings = self.embedder.embed(representations)
        self.store.store(topic, representations, embeddings)
        return StreamSemanticPipelineResult(
            representations=representations,
            embeddings=embeddings,
        )
