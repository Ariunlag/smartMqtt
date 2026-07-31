"""Isolated tests for stream semantic pipeline orchestration."""

import pytest
from services.embedding.base_model import BaseEmbeddingModel
from services.semantic import (
    RepresentationBuilder,
    RepresentationEmbedder,
    RepresentationEmbeddings,
    StreamRepresentations,
    StreamSemanticPipeline,
    StreamSemanticPipelineResult,
)

TOPIC = "factory/line1/sensor7"
TAGS = {"location": "Warehouse_01", "vendor": "Acme"}
FIELDS = {"temp": 22.5, "active": True}
REPRESENTATIONS = StreamRepresentations(
    value_only="Warehouse 01 | Acme | true | 22.5",
    key_only="location | vendor | active | temp",
    key_value=("location: Warehouse 01 | vendor: Acme | active: true | temp: 22.5"),
    schema="location: string | vendor: string | active: boolean | temp: numeric",
    numeric_key_only=("location: Warehouse 01 | vendor: Acme | active: true | temp"),
    topic_key_value=(
        "factory line1 sensor7 | location: Warehouse 01 | vendor: Acme | "
        "active: true | temp: 22.5"
    ),
)
EMBEDDINGS = RepresentationEmbeddings(
    value_only=(0.0, 0.5),
    key_only=(1.0, 1.5),
    key_value=(2.0, 2.5),
    schema=(3.0, 3.5),
    numeric_key_only=(4.0, 4.5),
    topic_key_value=(5.0, 5.5),
)


class FakeBuilder:
    def __init__(self, events, error=None):
        self.events = events
        self.error = error
        self.calls = []

    def build(self, topic, tags, fields):
        self.events.append("build")
        self.calls.append((topic, tags, fields))
        if self.error is not None:
            raise self.error
        return REPRESENTATIONS


class FakeEmbedder:
    def __init__(self, events, error=None):
        self.events = events
        self.error = error
        self.calls = []

    def embed(self, representations):
        self.events.append("embed")
        self.calls.append(representations)
        if self.error is not None:
            raise self.error
        return EMBEDDINGS


class FakeStore:
    def __init__(self, events, error=None):
        self.events = events
        self.error = error
        self.calls = []

    def store(self, topic, representations, embeddings):
        self.events.append("store")
        self.calls.append((topic, representations, embeddings))
        if self.error is not None:
            raise self.error


def test_process_calls_each_stage_once_in_order_and_returns_exact_results():
    events = []
    builder = FakeBuilder(events)
    embedder = FakeEmbedder(events)
    store = FakeStore(events)

    result = StreamSemanticPipeline(builder, embedder, store).process(
        TOPIC,
        TAGS,
        FIELDS,
    )

    assert events == ["build", "embed", "store"]
    assert builder.calls == [(TOPIC, TAGS, FIELDS)]
    assert embedder.calls == [REPRESENTATIONS]
    assert store.calls == [(TOPIC, REPRESENTATIONS, EMBEDDINGS)]
    assert result == StreamSemanticPipelineResult(
        representations=REPRESENTATIONS,
        embeddings=EMBEDDINGS,
    )
    assert result.representations is REPRESENTATIONS
    assert result.embeddings is EMBEDDINGS


def test_builder_exception_propagates_without_later_stages():
    events = []
    pipeline = StreamSemanticPipeline(
        FakeBuilder(events, RuntimeError("build failed")),
        FakeEmbedder(events),
        FakeStore(events),
    )

    with pytest.raises(RuntimeError, match="build failed"):
        pipeline.process(TOPIC, TAGS, FIELDS)

    assert events == ["build"]


def test_embedder_exception_propagates_without_storage():
    events = []
    pipeline = StreamSemanticPipeline(
        FakeBuilder(events),
        FakeEmbedder(events, RuntimeError("embed failed")),
        FakeStore(events),
    )

    with pytest.raises(RuntimeError, match="embed failed"):
        pipeline.process(TOPIC, TAGS, FIELDS)

    assert events == ["build", "embed"]


def test_store_exception_propagates():
    events = []
    pipeline = StreamSemanticPipeline(
        FakeBuilder(events),
        FakeEmbedder(events),
        FakeStore(events, RuntimeError("store failed")),
    )

    with pytest.raises(RuntimeError, match="store failed"):
        pipeline.process(TOPIC, TAGS, FIELDS)

    assert events == ["build", "embed", "store"]


class FakeEmbeddingModel(BaseEmbeddingModel):
    def __init__(self):
        self.calls = []

    def encode(self, texts):
        self.calls.append(list(texts))
        return [[float(index), float(len(text))] for index, text in enumerate(texts)]


def test_complete_in_process_flow_with_real_builder_and_embedder():
    events = []
    builder = RepresentationBuilder()
    model = FakeEmbeddingModel()
    embedder = RepresentationEmbedder(model)
    store = FakeStore(events)
    pipeline = StreamSemanticPipeline(builder, embedder, store)

    result = pipeline.process(TOPIC, TAGS, FIELDS)

    assert len(result.representations.as_dict()) == 6
    assert len(model.calls) == 1
    assert model.calls[0] == list(result.representations.as_dict().values())
    assert len(result.embeddings.as_dict()) == 6
    assert result.embeddings.value_only == (
        0.0,
        float(len(result.representations.value_only)),
    )
    assert store.calls == [(TOPIC, result.representations, result.embeddings)]
