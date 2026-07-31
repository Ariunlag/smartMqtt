"""Isolated tests for batched stream-representation embedding."""

from dataclasses import FrozenInstanceError

import pytest
from services.embedding.base_model import BaseEmbeddingModel
from services.semantic import (
    RepresentationBuilder,
    RepresentationEmbedder,
    RepresentationEmbeddings,
    StreamRepresentations,
)

REPRESENTATIONS = StreamRepresentations(
    value_only="Warehouse 01 | 22.5",
    key_only="location | temp",
    key_value="location: Warehouse 01 | temp: 22.5",
    schema="location: string | temp: numeric",
    numeric_key_only="location: Warehouse 01 | temp",
    topic_key_value=("factory line1 sensor7 | location: Warehouse 01 | temp: 22.5"),
)

EXPECTED_TEXTS = [
    REPRESENTATIONS.value_only,
    REPRESENTATIONS.key_only,
    REPRESENTATIONS.key_value,
    REPRESENTATIONS.schema,
    REPRESENTATIONS.numeric_key_only,
    REPRESENTATIONS.topic_key_value,
]


class FakeEmbeddingModel(BaseEmbeddingModel):
    def __init__(self, vectors=None):
        self.vectors = vectors
        self.calls = []

    def encode(self, texts):
        self.calls.append(list(texts))
        if self.vectors is not None:
            return self.vectors
        return [[float(index), float(index) + 0.5] for index, _ in enumerate(texts)]


def test_embeds_all_representations_once_in_deterministic_order():
    model = FakeEmbeddingModel()

    result = RepresentationEmbedder(model).embed(REPRESENTATIONS)

    assert model.calls == [EXPECTED_TEXTS]
    assert result.as_dict() == {
        "value_only": (0.0, 0.5),
        "key_only": (1.0, 1.5),
        "key_value": (2.0, 2.5),
        "schema": (3.0, 3.5),
        "numeric_key_only": (4.0, 4.5),
        "topic_key_value": (5.0, 5.5),
    }


def test_result_is_immutable():
    result = RepresentationEmbedder(FakeEmbeddingModel()).embed(REPRESENTATIONS)

    assert isinstance(result, RepresentationEmbeddings)
    assert isinstance(result.value_only, tuple)
    with pytest.raises(FrozenInstanceError):
        result.value_only = (9.0, 9.0)


def test_wrong_vector_count_raises_clear_error():
    model = FakeEmbeddingModel(vectors=[[1.0, 2.0]] * 5)

    with pytest.raises(ValueError, match="returned 5 vectors; expected 6"):
        RepresentationEmbedder(model).embed(REPRESENTATIONS)


def test_inconsistent_vector_dimensions_raise_clear_error():
    vectors = [[1.0, 2.0] for _ in range(6)]
    vectors[3] = [1.0]

    with pytest.raises(
        ValueError,
        match="vector for 'schema' has dimension 1; expected 2",
    ):
        RepresentationEmbedder(FakeEmbeddingModel(vectors)).embed(REPRESENTATIONS)


def test_empty_vector_raises_clear_error():
    vectors = [[1.0, 2.0] for _ in range(6)]
    vectors[4] = []

    with pytest.raises(
        ValueError,
        match="vector for 'numeric_key_only' is empty",
    ):
        RepresentationEmbedder(FakeEmbeddingModel(vectors)).embed(REPRESENTATIONS)


def test_embed_stream_matches_explicit_build_then_embed():
    topic = "factory/line1/sensor7"
    tags = {"location": "Warehouse_01", "vendor": "Acme"}
    fields = {"temp": 22.5, "active": True}
    builder = RepresentationBuilder()
    model = FakeEmbeddingModel()
    embedder = RepresentationEmbedder(model, builder)

    explicit = embedder.embed(builder.build(topic, tags, fields))
    convenient = embedder.embed_stream(topic, tags, fields)

    assert convenient == explicit
    assert len(model.calls) == 2
    assert model.calls[0] == model.calls[1]
