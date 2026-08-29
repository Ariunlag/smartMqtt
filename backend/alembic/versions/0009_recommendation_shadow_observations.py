"""persist shadow recommendation scores and feedback exposure provenance

Revision ID: 0009_recommendation_shadow
Revises: 0008_recommendation_models
Create Date: 2026-08-28
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0009_recommendation_shadow"
down_revision: str | None = "0008_recommendation_models"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE recommendation_shadow_observations (
            observation_id UUID PRIMARY KEY,
            shadow_run_id UUID NOT NULL,
            candidate_id UUID NOT NULL,
            candidate_version BIGINT NOT NULL,
            strategy_id TEXT NOT NULL,
            baseline_rank INTEGER NOT NULL CHECK (baseline_rank >= 1),
            membership_model_id UUID REFERENCES recommendation_model_versions(model_id),
            candidate_quality_model_id UUID REFERENCES recommendation_model_versions(model_id),
            membership_scores JSONB NOT NULL DEFAULT '{}'::jsonb,
            candidate_quality_score DOUBLE PRECISION,
            scoring_status TEXT NOT NULL CHECK (
                scoring_status IN ('SCORED', 'PARTIAL')
            ),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            FOREIGN KEY (candidate_id, candidate_version)
                REFERENCES recommended_class_candidate_versions(candidate_id, candidate_version)
                ON DELETE CASCADE,
            CHECK (
                membership_model_id IS NOT NULL
                OR candidate_quality_model_id IS NOT NULL
            )
        );

        CREATE INDEX idx_recommendation_shadow_run
            ON recommendation_shadow_observations(shadow_run_id, baseline_rank);

        CREATE INDEX idx_recommendation_shadow_candidate
            ON recommendation_shadow_observations(
                candidate_id, candidate_version, created_at DESC
            );

        CREATE INDEX idx_recommendation_shadow_models
            ON recommendation_shadow_observations(
                membership_model_id, candidate_quality_model_id, created_at DESC
            );

        ALTER TABLE recommended_class_feedback
            ADD COLUMN shadow_observation_id UUID
            REFERENCES recommendation_shadow_observations(observation_id)
            ON DELETE SET NULL;

        CREATE INDEX idx_recommended_feedback_shadow_observation
            ON recommended_class_feedback(shadow_observation_id)
            WHERE shadow_observation_id IS NOT NULL;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX idx_recommended_feedback_shadow_observation;
        ALTER TABLE recommended_class_feedback DROP COLUMN shadow_observation_id;
        DROP TABLE recommendation_shadow_observations;
        """
    )
