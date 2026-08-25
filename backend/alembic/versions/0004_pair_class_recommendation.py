"""pair-level class recommendation state

Revision ID: 0004_pair_class_recommendation
Revises: 0003_duplicate_canonical_id
Create Date: 2026-08-25
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004_pair_class_recommendation"
down_revision: str | None = "0003_duplicate_canonical_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE classes ADD COLUMN class_id TEXT;
        UPDATE classes
        SET class_id = md5('smartmqtt:class:' || name)
        WHERE class_id IS NULL;
        ALTER TABLE classes ALTER COLUMN class_id SET NOT NULL;
        ALTER TABLE classes ADD CONSTRAINT uq_classes_class_id UNIQUE (class_id);
        ALTER TABLE classes ADD COLUMN profile_version BIGINT NOT NULL DEFAULT 1;

        CREATE TABLE topic_representations (
            canonical_topic TEXT PRIMARY KEY,
            representation_version BIGINT NOT NULL,
            representation_fingerprint TEXT NOT NULL,
            representation_contract_version TEXT NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE TABLE class_recommendation_constraints (
            canonical_topic TEXT NOT NULL,
            class_id TEXT NOT NULL REFERENCES classes(class_id) ON DELETE CASCADE,
            rejected_topic_version BIGINT NOT NULL,
            rejected_class_profile_version BIGINT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (canonical_topic, class_id)
        );

        CREATE TABLE class_recommendation_dismissals (
            canonical_topic TEXT NOT NULL,
            class_id TEXT NOT NULL REFERENCES classes(class_id) ON DELETE CASCADE,
            dismissed_topic_version BIGINT NOT NULL,
            dismissed_class_profile_version BIGINT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (canonical_topic, class_id)
        );

        CREATE TABLE class_recommendation_actions (
            event_id UUID PRIMARY KEY,
            occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            action_type TEXT NOT NULL,
            canonical_topic TEXT,
            original_topic TEXT,
            class_id TEXT,
            class_name TEXT,
            class_profile_version_before BIGINT,
            class_profile_version_after BIGINT,
            topic_representation_version BIGINT,
            recommendation_id TEXT,
            recommendation_algorithm_version TEXT,
            overall_score DOUBLE PRECISION,
            channel_scores JSONB,
            coverage JSONB,
            matched_pairs JSONB,
            duplicate_state TEXT,
            details JSONB NOT NULL DEFAULT '{}'::jsonb
        );
        CREATE INDEX idx_class_recommendation_actions_topic
            ON class_recommendation_actions(canonical_topic, occurred_at);
        CREATE INDEX idx_class_recommendation_actions_class
            ON class_recommendation_actions(class_id, occurred_at);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE class_recommendation_actions;
        DROP TABLE class_recommendation_dismissals;
        DROP TABLE class_recommendation_constraints;
        DROP TABLE topic_representations;
        ALTER TABLE classes DROP COLUMN profile_version;
        ALTER TABLE classes DROP CONSTRAINT uq_classes_class_id;
        ALTER TABLE classes DROP COLUMN class_id;
        """
    )
