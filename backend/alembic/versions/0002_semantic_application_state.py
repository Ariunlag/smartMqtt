"""semantic application state

Revision ID: 0002_semantic_application_state
Revises: 0001_baseline
Create Date: 2026-07-31
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002_semantic_application_state"
down_revision: str | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE semantic_application_state (
            state_key TEXT PRIMARY KEY,
            schema_version INTEGER NOT NULL,
            generation BIGINT NOT NULL,
            model_fingerprint TEXT NOT NULL,
            representation_contract_version TEXT NOT NULL,
            policy_config JSONB NOT NULL,
            payload JSONB NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE semantic_application_state")
