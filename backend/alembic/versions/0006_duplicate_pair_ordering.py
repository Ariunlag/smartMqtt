"""make duplicate pair ordering deterministic across database collations

Revision ID: 0006_duplicate_pair_ordering
Revises: 0005_pgvector_embeddings
Create Date: 2026-08-26
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006_duplicate_pair_ordering"
down_revision: str | None = "0005_pgvector_embeddings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The baseline used CHECK (topic_a < topic_b), which depends on the database
    # locale. Python canonicalizes duplicate pairs by deterministic string order,
    # so locale-aware PostgreSQL ordering can disagree for punctuation/digits.
    op.execute("ALTER TABLE duplicates DROP CONSTRAINT IF EXISTS duplicates_check")
    op.execute(
        "ALTER TABLE duplicates DROP CONSTRAINT IF EXISTS duplicates_topic_order_check"
    )
    op.execute(
        '''
        ALTER TABLE duplicates
        ADD CONSTRAINT duplicates_topic_order_check
        CHECK ((topic_a COLLATE "C") < (topic_b COLLATE "C"))
        '''
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE duplicates DROP CONSTRAINT IF EXISTS duplicates_topic_order_check"
    )
    op.execute(
        "ALTER TABLE duplicates ADD CONSTRAINT duplicates_check CHECK (topic_a < topic_b)"
    )
