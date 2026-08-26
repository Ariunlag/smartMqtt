import json

import pytest

from services.database.vector import PostgresVectorStore


class FakeDatabase:
    def __init__(self):
        self.executed = []
        self.rows = []
        self.row = None

    def execute(self, sql, params=()):
        self.executed.append((sql, params))
        return 1

    def fetch_all(self, sql, params=()):
        self.executed.append((sql, params))
        return list(self.rows)

    def fetch_one(self, sql, params=()):
        self.executed.append((sql, params))
        return self.row


def _vector(value=0.0):
    return [value] * 384


def test_pgvector_store_upserts_and_uses_cosine_ann_query():
    database = FakeDatabase()
    store = PostgresVectorStore(database)
    store.upsert(
        "topic_embeddings",
        "topic/a",
        _vector(0.25),
        {"topic": "topic/a", "tags": {"unit": "c"}},
    )

    sql, params = database.executed[-1]
    assert "INSERT INTO topic_embeddings" in sql
    assert "%s::vector" in sql
    assert len(json.loads(params[1])) == 384
    assert json.loads(params[2])["topic"] == "topic/a"

    database.rows = [
        {
            "identity": "topic/b",
            "payload": {"topic": "topic/b"},
            "embedding": json.dumps(_vector(0.5)),
            "score": 0.91,
        }
    ]
    points = store.nearest_many("topic_embeddings", _vector(0.5), limit=5)
    assert points[0].id == "topic/b"
    assert points[0].score == pytest.approx(0.91)
    assert points[0].vector == _vector(0.5)
    sql, _ = database.executed[-1]
    assert "embedding <=>" in sql
    assert "ORDER BY" in sql


def test_pgvector_store_filters_delete_in_sql_instead_of_scanning_points():
    database = FakeDatabase()
    store = PostgresVectorStore(database)

    store.delete_where("class_pair_embeddings", {"canonical_topic": "topic/a"})

    sql, params = database.executed[-1]
    assert "DELETE FROM class_pair_embeddings" in sql
    assert "payload @> %s::jsonb" in sql
    assert json.loads(params[0]) == {"canonical_topic": "topic/a"}


def test_pgvector_store_rejects_unknown_collection_and_wrong_dimension():
    store = PostgresVectorStore(FakeDatabase())
    with pytest.raises(ValueError, match="Unsupported vector collection"):
        store.all_points("not-a-collection")
    with pytest.raises(ValueError, match="Embedding dimension mismatch"):
        store.upsert("topic_embeddings", "topic/a", [1.0, 2.0], {})
