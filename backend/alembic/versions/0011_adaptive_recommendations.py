"""Environment-local evidence, editable groups and learned weights."""

from alembic import op

revision = "0011_adaptive_recommendations"
down_revision = "0010_recommendation_live"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE adaptive_topics (
            environment_id TEXT NOT NULL,
            topic TEXT NOT NULL,
            fingerprint TEXT NOT NULL,
            tags JSONB NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY(environment_id, topic)
        );
        CREATE TABLE adaptive_evidence (
            environment_id TEXT NOT NULL,
            topic TEXT NOT NULL,
            provider_id TEXT NOT NULL,
            provider_version TEXT NOT NULL,
            entity TEXT NOT NULL,
            embedding vector,
            payload JSONB NOT NULL,
            PRIMARY KEY(environment_id, topic, provider_id, entity),
            FOREIGN KEY(environment_id, topic) REFERENCES adaptive_topics
                ON DELETE CASCADE
        );
        CREATE TABLE adaptive_groups (
            environment_id TEXT NOT NULL,
            group_id TEXT NOT NULL,
            revision BIGINT NOT NULL DEFAULT 1,
            state JSONB NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY(environment_id, group_id)
        );
        CREATE TABLE adaptive_events (
            sequence BIGSERIAL PRIMARY KEY,
            event_id UUID NOT NULL UNIQUE,
            environment_id TEXT NOT NULL,
            group_id TEXT NOT NULL,
            action TEXT NOT NULL,
            topic TEXT,
            label INTEGER CHECK(label IN (0, 1)),
            evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
            details JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX adaptive_events_environment_sequence
            ON adaptive_events(environment_id, sequence);
        CREATE TABLE adaptive_models (
            environment_id TEXT NOT NULL,
            manifest_id TEXT NOT NULL,
            version BIGINT NOT NULL,
            model JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY(environment_id, manifest_id, version)
        );
        ALTER TABLE classes ADD COLUMN recommendation_environment TEXT;
    """)


def downgrade():
    op.execute("""
        ALTER TABLE classes DROP COLUMN recommendation_environment;
        DROP TABLE adaptive_models;
        DROP TABLE adaptive_events;
        DROP TABLE adaptive_groups;
        DROP TABLE adaptive_evidence;
        DROP TABLE adaptive_topics;
    """)
