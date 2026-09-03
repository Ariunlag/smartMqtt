"""PostgreSQL + pgvector storage for active dense embedding collections."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

from config import config
from services.database.postgres import postgres_client

TOPIC_COLLECTION = "topic_embeddings"

_COLLECTION_TABLES = {
    TOPIC_COLLECTION: "topic_embeddings",
    "class_pair_embeddings": "class_pair_embeddings",
    "class_pair_prototypes": "class_pair_prototypes",
    "class_stream_context_prototypes": "class_stream_context_prototypes",
}


def deterministic_vector_identity(namespace: str, *parts: object) -> str:
    """Return a fixed-size, PostgreSQL TEXT-safe identity for composite keys."""
    material = json.dumps(
        [str(part) for part in parts],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"influxai:{namespace}:{material}"))


@dataclass(frozen=True, slots=True)
class VectorPoint:
    id: str
    vector: list[float]
    payload: dict[str, Any]
    score: float | None = None


class PostgresVectorStore:
    """Small collection-style adapter backed by pgvector tables."""

    def __init__(self, database=postgres_client) -> None:
        self.database = database
        self.dimension = config.EMBEDDING_DIMENSION

    def _table(self, collection: str) -> str:
        try:
            return _COLLECTION_TABLES[collection]
        except KeyError as exc:
            raise ValueError(f"Unsupported vector collection: {collection}") from exc

    def _vector_literal(self, vector) -> str:
        values = [float(value) for value in vector]
        if len(values) != self.dimension:
            raise ValueError(
                f"Embedding dimension mismatch: expected {self.dimension}, got {len(values)}"
            )
        return "[" + ",".join(format(value, ".17g") for value in values) + "]"

    @staticmethod
    def _decode_vector(value: str) -> list[float]:
        return [float(item) for item in json.loads(value)]

    @classmethod
    def _decode_points(cls, rows) -> list[VectorPoint]:
        return [
            VectorPoint(
                id=row["identity"],
                vector=cls._decode_vector(row["embedding"]),
                payload=dict(row["payload"] or {}),
                score=float(row["score"]) if row.get("score") is not None else None,
            )
            for row in rows
        ]

    def _fetch_one(self, sql: str, params=(), *, conn=None):
        if conn is not None:
            return conn.execute(sql, params).fetchone()
        return self.database.fetch_one(sql, params)

    def _fetch_all(self, sql: str, params=(), *, conn=None):
        if conn is not None:
            return list(conn.execute(sql, params).fetchall())
        return self.database.fetch_all(sql, params)

    def _execute(self, sql: str, params=(), *, conn=None) -> int:
        if conn is not None:
            return conn.execute(sql, params).rowcount
        return self.database.execute(sql, params)

    def upsert(
        self,
        collection: str,
        identity: str,
        vector: list[float],
        payload: dict[str, Any],
        *,
        conn=None,
    ) -> None:
        table = self._table(collection)
        literal = self._vector_literal(vector)
        self._execute(
            f"""
            INSERT INTO {table}(identity, embedding, payload)
            VALUES (%s, %s::vector, %s::jsonb)
            ON CONFLICT (identity) DO UPDATE SET
                embedding = EXCLUDED.embedding,
                payload = EXCLUDED.payload,
                updated_at = now()
            """,
            (identity, literal, json.dumps(payload)),
            conn=conn,
        )

    def nearest(
        self,
        collection: str,
        vector: list[float],
        *,
        payload_filter: dict[str, Any] | None = None,
        conn=None,
    ):
        rows = self.nearest_many(
            collection,
            vector,
            limit=1,
            payload_filter=payload_filter,
            conn=conn,
        )
        return rows[0] if rows else None

    def nearest_many(
        self,
        collection: str,
        vector: list[float],
        limit: int = 10,
        *,
        payload_filter: dict[str, Any] | None = None,
        conn=None,
    ) -> list[VectorPoint]:
        if limit <= 0:
            return []
        table = self._table(collection)
        literal = self._vector_literal(vector)
        where = ""
        params: list[Any] = [literal]
        if payload_filter:
            where = "WHERE payload @> %s::jsonb"
            params.append(json.dumps(payload_filter))
        params.extend((literal, int(limit)))
        rows = self._fetch_all(
            f"""
            SELECT identity, payload, embedding::text AS embedding,
                   1 - (embedding <=> %s::vector) AS score
            FROM {table}
            {where}
            ORDER BY embedding <=> %s::vector
            LIMIT %s
            """,
            tuple(params),
            conn=conn,
        )
        return self._decode_points(rows)

    def retrieve(self, collection: str, identity: str, *, conn=None):
        table = self._table(collection)
        row = self._fetch_one(
            f"""
            SELECT identity, payload, embedding::text AS embedding
            FROM {table} WHERE identity = %s
            """,
            (identity,),
            conn=conn,
        )
        if row is None:
            return None
        return VectorPoint(
            id=row["identity"],
            vector=self._decode_vector(row["embedding"]),
            payload=dict(row["payload"] or {}),
        )

    def retrieve_many(
        self,
        collection: str,
        identities: list[str] | tuple[str, ...],
        *,
        conn=None,
    ) -> list[VectorPoint]:
        unique = tuple(sorted(set(identities)))
        if not unique:
            return []
        table = self._table(collection)
        rows = self._fetch_all(
            f"""
            SELECT identity, payload, embedding::text AS embedding
            FROM {table}
            WHERE identity = ANY(%s::text[])
            ORDER BY identity
            """,
            (list(unique),),
            conn=conn,
        )
        return self._decode_points(rows)

    def points_where(
        self,
        collection: str,
        payload_filter: dict[str, Any],
        *,
        conn=None,
    ) -> list[VectorPoint]:
        if not payload_filter:
            return self.all_points(collection, conn=conn)
        table = self._table(collection)
        rows = self._fetch_all(
            f"""
            SELECT identity, payload, embedding::text AS embedding
            FROM {table}
            WHERE payload @> %s::jsonb
            ORDER BY identity
            """,
            (json.dumps(payload_filter),),
            conn=conn,
        )
        return self._decode_points(rows)

    def points_by_payload_values(
        self,
        collection: str,
        payload_key: str,
        values: list[str] | tuple[str, ...],
        *,
        conn=None,
    ) -> list[VectorPoint]:
        """Bulk-read only rows whose JSON payload key is in the requested values.

        This intentionally performs one database round-trip for a set of topics. The
        single-value path should prefer ``points_where`` so PostgreSQL can directly use
        the existing JSONB GIN containment index.
        """
        unique = tuple(sorted(set(values)))
        if not unique:
            return []
        table = self._table(collection)
        rows = self._fetch_all(
            f"""
            SELECT identity, payload, embedding::text AS embedding
            FROM {table}
            WHERE payload ->> %s = ANY(%s::text[])
            ORDER BY identity
            """,
            (payload_key, list(unique)),
            conn=conn,
        )
        return self._decode_points(rows)

    def delete(self, collection: str, identity: str, *, conn=None) -> None:
        table = self._table(collection)
        self._execute(
            f"DELETE FROM {table} WHERE identity = %s",
            (identity,),
            conn=conn,
        )

    def delete_where(
        self,
        collection: str,
        payload: dict[str, Any],
        *,
        conn=None,
    ) -> None:
        table = self._table(collection)
        self._execute(
            f"DELETE FROM {table} WHERE payload @> %s::jsonb",
            (json.dumps(payload),),
            conn=conn,
        )

    def all_points(self, collection: str, *, conn=None) -> list[VectorPoint]:
        table = self._table(collection)
        rows = self._fetch_all(
            f"""
            SELECT identity, payload, embedding::text AS embedding
            FROM {table} ORDER BY identity
            """,
            conn=conn,
        )
        return self._decode_points(rows)


vector_store = PostgresVectorStore()
