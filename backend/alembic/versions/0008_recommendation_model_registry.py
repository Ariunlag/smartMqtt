"""persist versioned recommendation learning model artifacts

Revision ID: 0008_recommendation_models
Revises: 0007_recommended_feedback
Create Date: 2026-08-28
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0008_recommendation_models"
down_revision: str | None = "0007_recommended_feedback"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE recommendation_model_versions (
            model_id UUID PRIMARY KEY,
            objective TEXT NOT NULL CHECK (
                objective IN ('membership', 'candidate_quality')
            ),
            model_version BIGINT NOT NULL,
            feature_contract_version TEXT NOT NULL,
            dataset_fingerprint TEXT NOT NULL,
            model_type TEXT NOT NULL,
            artifact JSONB NOT NULL,
            training_report JSONB NOT NULL,
            gate_report JSONB NOT NULL,
            status TEXT NOT NULL DEFAULT 'CANDIDATE' CHECK (
                status IN ('CANDIDATE', 'OFFLINE_APPROVED', 'RETIRED')
            ),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            approved_at TIMESTAMPTZ,
            retired_at TIMESTAMPTZ,
            UNIQUE (objective, model_version),
            UNIQUE (
                objective,
                feature_contract_version,
                dataset_fingerprint,
                model_type
            )
        );

        CREATE UNIQUE INDEX uq_recommendation_model_offline_approved
            ON recommendation_model_versions(objective)
            WHERE status = 'OFFLINE_APPROVED';

        CREATE INDEX idx_recommendation_model_objective_created
            ON recommendation_model_versions(objective, created_at DESC);

        CREATE TABLE recommendation_model_events (
            event_id UUID PRIMARY KEY,
            model_id UUID NOT NULL REFERENCES recommendation_model_versions(model_id)
                ON DELETE CASCADE,
            event_type TEXT NOT NULL CHECK (
                event_type IN ('REGISTERED', 'OFFLINE_APPROVED', 'RETIRED')
            ),
            reason TEXT,
            details JSONB NOT NULL DEFAULT '{}'::jsonb,
            occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE INDEX idx_recommendation_model_events
            ON recommendation_model_events(model_id, occurred_at);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE recommendation_model_events;
        DROP TABLE recommendation_model_versions;
        """
    )
