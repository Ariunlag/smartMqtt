import logging
from contextlib import contextmanager
from threading import Lock
from typing import Iterator

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from config import config


logger = logging.getLogger(__name__)


class PostgresClient:
    def __init__(self, dsn: str):
        self.dsn = dsn
        self._ready = False
        self._pool: ConnectionPool | None = None
        self._pool_lock = Lock()

    def _get_pool(self) -> ConnectionPool:
        with self._pool_lock:
            if self._pool is None:
                # min_size=0 keeps startup lazy: an unavailable PostgreSQL instance
                # does not block module import or application construction.
                self._pool = ConnectionPool(
                    conninfo=self.dsn,
                    min_size=0,
                    max_size=config.POSTGRES_POOL_MAX_SIZE,
                    timeout=config.POSTGRES_POOL_TIMEOUT,
                    kwargs={"row_factory": dict_row},
                    open=True,
                )
            return self._pool

    @contextmanager
    def _connection(self) -> Iterator[psycopg.Connection]:
        pool = self._get_pool()
        with pool.connection(timeout=config.POSTGRES_POOL_TIMEOUT) as conn:
            yield conn

    def connect(self):
        # Connection establishment must NOT create or mutate schema — the schema
        # is owned by Alembic migrations (`alembic upgrade head`). Here we only
        # verify connectivity and readiness.
        try:
            with self._connection() as conn:
                conn.execute("SELECT 1")
            self._ready = True
            logger.info("[PostgresClient] Connected")
        except Exception as exc:
            self._ready = False
            logger.warning("[PostgresClient] Connection failed: %s", exc)

    def disconnect(self):
        with self._pool_lock:
            pool = self._pool
            self._pool = None
        if pool is not None:
            pool.close()
        self._ready = False

    def check_health(self) -> bool:
        try:
            with self._connection() as conn:
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
        with self._connection() as conn:
            yield conn

    def fetch_all(self, sql: str, params=()):
        with self._connection() as conn:
            return list(conn.execute(sql, params).fetchall())

    def fetch_one(self, sql: str, params=()):
        with self._connection() as conn:
            return conn.execute(sql, params).fetchone()

    def execute(self, sql: str, params=()) -> int:
        with self._connection() as conn:
            cursor = conn.execute(sql, params)
            return cursor.rowcount


postgres_client = PostgresClient(config.POSTGRES_DSN)
