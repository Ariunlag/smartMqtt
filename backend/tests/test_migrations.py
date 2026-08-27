"""Alembic migration tests (issue #9 / Phase 2 DB foundation).

These require a disposable PostgreSQL database with the pgvector extension available.
Set TEST_DATABASE_URL (or POSTGRES_TEST_DSN) to run them; otherwise they are skipped.
The target database is wiped between tests, so never point these at a real database.
"""

import os
from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config

BACKEND_DIR = Path(__file__).resolve().parents[1]

APP_TABLES = [
    "streams",
    "ignored_topics",
    "detected_topics",
    "classes",
    "class_topics",
    "duplicates",
    "tag_groups",
    "tag_group_values",
    "tag_group_topics",
    "semantic_application_state",
    "duplicate_canonical_topics",
    "topic_representations",
    "class_recommendation_constraints",
    "class_recommendation_dismissals",
    "class_recommendation_actions",
    "topic_embeddings",
    "tag_key_value_embeddings",
    "tag_group_centroids",
    "class_pair_embeddings",
    "class_pair_prototypes",
    "class_stream_context_prototypes",
]

HEAD_REVISION = "0006_duplicate_pair_ordering"


def _make_config(url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    os.environ["POSTGRES_DSN"] = url
    return cfg


def _drop_everything(url: str) -> None:
    with psycopg.connect(url) as conn:
        with conn.cursor() as cur:
            for table in APP_TABLES:
                cur.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
            cur.execute("DROP TABLE IF EXISTS alembic_version")
        conn.commit()


def _table_exists(url: str, table: str) -> bool:
    with psycopg.connect(url) as conn:
        row = conn.execute(
            "SELECT to_regclass(%s) IS NOT NULL AS present", (f"public.{table}",)
        ).fetchone()
    return bool(row[0])


def _alembic_version(url: str):
    with psycopg.connect(url) as conn:
        if not _table_exists(url, "alembic_version"):
            return None
        row = conn.execute("SELECT version_num FROM alembic_version").fetchone()
    return row[0] if row else None


@pytest.fixture()
def pg_url():
    url = os.getenv("TEST_DATABASE_URL") or os.getenv("POSTGRES_TEST_DSN")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    try:
        with psycopg.connect(url, connect_timeout=3) as conn:
            conn.execute("SELECT 1")
            available = conn.execute(
                "SELECT EXISTS(SELECT 1 FROM pg_available_extensions WHERE name = 'vector')"
            ).fetchone()[0]
            if not available:
                pytest.skip("pgvector extension is not available on the test database")
    except Exception as exc:  # noqa: BLE001  # pragma: no cover
        pytest.skip(f"test database not reachable: {exc}")
    _drop_everything(url)
    yield url
    _drop_everything(url)


def test_clean_database_upgrades_to_head(pg_url):
    command.upgrade(_make_config(pg_url), "head")
    assert _alembic_version(pg_url) == HEAD_REVISION
    for table in APP_TABLES:
        assert _table_exists(pg_url, table), table
    with psycopg.connect(pg_url) as conn:
        extension = conn.execute(
            "SELECT extname FROM pg_extension WHERE extname = 'vector'"
        ).fetchone()
        constraint = conn.execute(
            """
            SELECT pg_get_constraintdef(oid)
            FROM pg_constraint
            WHERE conrelid = 'duplicates'::regclass
              AND conname = 'duplicates_topic_order_check'
            """
        ).fetchone()
    assert extension and extension[0] == "vector"
    assert constraint and 'COLLATE "C"' in constraint[0]


def test_existing_schema_adopts_baseline_without_data_loss(pg_url):
    with psycopg.connect(pg_url) as conn:
        conn.execute(
            "CREATE TABLE streams ("
            "topic TEXT PRIMARY KEY, enabled BOOLEAN NOT NULL DEFAULT TRUE,"
            "created_at TIMESTAMPTZ NOT NULL DEFAULT now())"
        )
        conn.execute("INSERT INTO streams(topic) VALUES ('keep/me')")
        conn.commit()

    command.upgrade(_make_config(pg_url), "head")

    assert _alembic_version(pg_url) == HEAD_REVISION
    with psycopg.connect(pg_url) as conn:
        row = conn.execute("SELECT topic FROM streams").fetchone()
    assert row[0] == "keep/me"


def test_repeated_upgrade_is_idempotent(pg_url):
    cfg = _make_config(pg_url)
    command.upgrade(cfg, "head")
    command.upgrade(cfg, "head")
    assert _alembic_version(pg_url) == HEAD_REVISION


def test_downgrade_removes_baseline(pg_url):
    cfg = _make_config(pg_url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    assert _alembic_version(pg_url) is None
    for table in APP_TABLES:
        assert not _table_exists(pg_url, table), table
