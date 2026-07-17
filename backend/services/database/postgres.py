import logging
from contextlib import contextmanager
from typing import Iterator

import psycopg
from psycopg.rows import dict_row

from config import config


logger = logging.getLogger(__name__)


class PostgresClient:
    def __init__(self, dsn: str):
        self.dsn = dsn
        self._ready = False

    def _connect(self):
        return psycopg.connect(self.dsn, row_factory=dict_row)

    def connect(self):
        # Connection establishment must NOT create or mutate schema — the schema
        # is owned by Alembic migrations (`alembic upgrade head`). Here we only
        # verify connectivity and readiness.
        try:
            with self._connect() as conn:
                conn.execute("SELECT 1")
            self._ready = True
            logger.info("[PostgresClient] Connected")
        except Exception as exc:
            self._ready = False
            logger.warning("[PostgresClient] Connection failed: %s", exc)

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
