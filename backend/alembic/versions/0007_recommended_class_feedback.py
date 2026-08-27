"""persist recommended candidate versions and user feedback

Revision ID: 0007_recommended_feedback
Revises: 0006_duplicate_pair_ordering
Create Date: 2026-08-27
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007_recommended_feedback"
down_revision: str | None = "0006_duplicate_pair_ordering"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE recommended_class_candidates (
            candidate_id UUID PRIMARY KEY,
            strategy_id TEXT NOT NULL,
            current_version BIGINT NOT NULL DEFAULT 1,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE TABLE recommended_class_candidate_versions (
            candidate_id UUID NOT NULL REFERENCES recommended_class_candidates(candidate_id)
                ON DELETE CASCADE,
            candidate_version BIGINT NOT NULL,
            member_topics JSONB NOT NULL,
            discovery_evidence JSONB NOT NULL,
            evidence_snapshot JSONB NOT NULL,
            snapshot_fingerprint TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (candidate_id, candidate_version)
        );
        CREATE UNIQUE INDEX uq_recommended_candidate_snapshot
            ON recommended_class_candidate_versions(candidate_id, snapshot_fingerprint);

        CREATE TABLE recommended_class_feedback (
            feedback_id UUID PRIMARY KEY,
            candidate_id UUID NOT NULL,
            candidate_version BIGINT NOT NULL,
            action_type TEXT NOT NULL CHECK (
                action_type IN (
                    'KEEP_TOPIC',
                    'REMOVE_TOPIC',
                    'ACCEPT_CANDIDATE',
                    'DISMISS_CANDIDATE'
                )
            ),
            topic TEXT,
            evidence_snapshot JSONB NOT NULL,
            occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            FOREIGN KEY (candidate_id, candidate_version)
                REFERENCES recommended_class_candidate_versions(candidate_id, candidate_version)
                ON DELETE CASCADE,
            CHECK (
                (action_type IN ('KEEP_TOPIC', 'REMOVE_TOPIC') AND topic IS NOT NULL)
                OR
                (action_type IN ('ACCEPT_CANDIDATE', 'DISMISS_CANDIDATE') AND topic IS NULL)
            )
        );
        CREATE INDEX idx_recommended_feedback_candidate
            ON recommended_class_feedback(candidate_id, candidate_version, occurred_at);
        CREATE INDEX idx_recommended_feedback_action
            ON recommended_class_feedback(action_type, occurred_at);
        CREATE INDEX idx_recommended_feedback_topic
            ON recommended_class_feedback(topic, occurred_at)
            WHERE topic IS NOT NULL;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE recommended_class_feedback;
        DROP TABLE recommended_class_candidate_versions;
        DROP TABLE recommended_class_candidates;
        """
    )
