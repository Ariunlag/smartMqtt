"""durable duplicate canonical identity

Revision ID: 0003_duplicate_canonical_id
Revises: 0002_semantic_application_state
Create Date: 2026-08-23
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003_duplicate_canonical_id"
down_revision: str | None = "0002_semantic_application_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE duplicate_canonical_topics (
            topic TEXT PRIMARY KEY,
            canonical_topic TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CHECK (topic <> ''),
            CHECK (canonical_topic <> '')
        );
        CREATE INDEX idx_duplicate_canonical_root
            ON duplicate_canonical_topics(canonical_topic);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE duplicate_canonical_topics")
