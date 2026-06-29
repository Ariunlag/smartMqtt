from contextlib import contextmanager
from typing import Iterator

import psycopg
from psycopg.rows import dict_row

from config import config


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS streams (
    topic TEXT PRIMARY KEY,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ignored_topics (
    topic TEXT PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS detected_topics (
    topic TEXT PRIMARY KEY,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS classes (
    name TEXT PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS class_topics (
    class_name TEXT NOT NULL REFERENCES classes(name) ON DELETE CASCADE,
    topic TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (class_name, topic)
);

CREATE TABLE IF NOT EXISTS duplicates (
    topic_a TEXT NOT NULL,
    topic_b TEXT NOT NULL,
    score DOUBLE PRECISION NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING'
        CHECK (status IN ('PENDING', 'CONFIRMED_DUPLICATE', 'NOT_DUPLICATE')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (topic_a, topic_b),
    CHECK (topic_a < topic_b)
);

CREATE TABLE IF NOT EXISTS tag_groups (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tag_group_values (
    group_id BIGINT NOT NULL REFERENCES tag_groups(id) ON DELETE CASCADE,
    tag_key TEXT NOT NULL,
    tag_value TEXT NOT NULL,
    PRIMARY KEY (group_id, tag_key, tag_value)
);

CREATE TABLE IF NOT EXISTS tag_group_topics (
    group_id BIGINT NOT NULL REFERENCES tag_groups(id) ON DELETE CASCADE,
    topic TEXT NOT NULL,
    PRIMARY KEY (group_id, topic)
);

CREATE INDEX IF NOT EXISTS idx_duplicates_status ON duplicates(status);
CREATE INDEX IF NOT EXISTS idx_tag_group_topics_topic ON tag_group_topics(topic);
"""


class PostgresClient:
    def __init__(self, dsn: str):
        self.dsn = dsn
        self._ready = False

    def _connect(self):
        return psycopg.connect(self.dsn, row_factory=dict_row)

    def connect(self):
        try:
            with self._connect() as conn:
                conn.execute(SCHEMA_SQL)
            self._ready = True
            print("[PostgresClient] Schema ready")
        except Exception as exc:
            self._ready = False
            print(f"[PostgresClient] Connection failed: {exc}")

    def disconnect(self):
        self._ready = False

    def check_health(self) -> bool:
        try:
            with self._connect() as conn:
                row = conn.execute(
                    """
                    SELECT to_regclass('public.streams') IS NOT NULL AS ready
                    """
                ).fetchone()
            self._ready = bool(row and row["ready"])
        except Exception:
            self._ready = False
        return self._ready

    @contextmanager
    def transaction(self) -> Iterator[psycopg.Connection]:
        with self._connect() as conn:
            yield conn

    def fetch_all(self, sql: str, params=()):
        with self._connect() as conn:
            return list(conn.execute(sql, params).fetchall())

    def fetch_one(self, sql: str, params=()):
        with self._connect() as conn:
            return conn.execute(sql, params).fetchone()

    def execute(self, sql: str, params=()) -> int:
        with self._connect() as conn:
            cursor = conn.execute(sql, params)
            return cursor.rowcount


postgres_client = PostgresClient(config.POSTGRES_DSN)
