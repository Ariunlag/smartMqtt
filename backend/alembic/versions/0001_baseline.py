"""baseline schema

Represents the PostgreSQL schema previously created at startup by
PostgresClient. Uses IF NOT EXISTS so an existing database (created by the old
startup path) adopts this baseline without data loss, while a fresh database is
created from scratch. Alembic then records the version in alembic_version.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-07-17

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


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

# Reverse dependency order for a clean teardown below the baseline.
DROP_SQL = """
DROP INDEX IF EXISTS idx_tag_group_topics_topic;
DROP INDEX IF EXISTS idx_duplicates_status;
DROP TABLE IF EXISTS tag_group_topics;
DROP TABLE IF EXISTS tag_group_values;
DROP TABLE IF EXISTS tag_groups;
DROP TABLE IF EXISTS duplicates;
DROP TABLE IF EXISTS class_topics;
DROP TABLE IF EXISTS classes;
DROP TABLE IF EXISTS detected_topics;
DROP TABLE IF EXISTS ignored_topics;
DROP TABLE IF EXISTS streams;
"""


def upgrade() -> None:
    op.execute(SCHEMA_SQL)


def downgrade() -> None:
    op.execute(DROP_SQL)
