"""allow explicit topic-add recommendation feedback

Revision ID: 0012_explicit_topic_add_feedback
Revises: 0011_adaptive_recommendations
Create Date: 2026-09-21
"""

from alembic import op

revision = "0012_explicit_topic_add_feedback"
down_revision = "0011_adaptive_recommendations"
branch_labels = None
depends_on = None


def _drop_action_checks() -> None:
    op.execute(
        """
        DO $$
        DECLARE check_name text;
        BEGIN
            FOR check_name IN
                SELECT conname
                FROM pg_constraint
                WHERE conrelid = 'recommended_class_feedback'::regclass
                  AND contype = 'c'
                  AND pg_get_constraintdef(oid) ILIKE '%action_type%'
            LOOP
                EXECUTE format(
                    'ALTER TABLE recommended_class_feedback DROP CONSTRAINT %I',
                    check_name
                );
            END LOOP;
        END $$;
        """
    )


def upgrade() -> None:
    _drop_action_checks()
    op.execute(
        """
        ALTER TABLE recommended_class_feedback
        ADD CONSTRAINT ck_recommended_feedback_action_type
            CHECK (
                action_type IN (
                    'KEEP_TOPIC',
                    'ADD_TOPIC',
                    'REMOVE_TOPIC',
                    'ACCEPT_CANDIDATE',
                    'DISMISS_CANDIDATE'
                )
            ),
        ADD CONSTRAINT ck_recommended_feedback_topic_scope
            CHECK (
                (
                    action_type IN ('KEEP_TOPIC', 'ADD_TOPIC', 'REMOVE_TOPIC')
                    AND topic IS NOT NULL
                )
                OR
                (
                    action_type IN ('ACCEPT_CANDIDATE', 'DISMISS_CANDIDATE')
                    AND topic IS NULL
                )
            );
        """
    )


def downgrade() -> None:
    _drop_action_checks()
    op.execute(
        """
        ALTER TABLE recommended_class_feedback
        ADD CONSTRAINT ck_recommended_feedback_action_type
            CHECK (
                action_type IN (
                    'KEEP_TOPIC',
                    'REMOVE_TOPIC',
                    'ACCEPT_CANDIDATE',
                    'DISMISS_CANDIDATE'
                )
            ),
        ADD CONSTRAINT ck_recommended_feedback_topic_scope
            CHECK (
                (
                    action_type IN ('KEEP_TOPIC', 'REMOVE_TOPIC')
                    AND topic IS NOT NULL
                )
                OR
                (
                    action_type IN ('ACCEPT_CANDIDATE', 'DISMISS_CANDIDATE')
                    AND topic IS NULL
                )
            );
        """
    )
