"""persist explicit live ranking deployment and exposure provenance

Revision ID: 0010_recommendation_live
Revises: 0009_recommendation_shadow
Create Date: 2026-08-28
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0010_recommendation_live"
down_revision: str | None = "0009_recommendation_shadow"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE recommended_class_feedback
            DROP CONSTRAINT IF EXISTS recommended_class_feedback_shadow_observation_id_fkey;
        ALTER TABLE recommended_class_feedback
            ADD CONSTRAINT recommended_class_feedback_shadow_observation_id_fkey
            FOREIGN KEY (shadow_observation_id)
            REFERENCES recommendation_shadow_observations(observation_id)
            ON DELETE SET NULL;

        CREATE UNIQUE INDEX uq_recommendation_shadow_run_candidate
            ON recommendation_shadow_observations(
                shadow_run_id, candidate_id, candidate_version
            );

        CREATE TABLE recommendation_live_deployments (
            objective TEXT PRIMARY KEY CHECK (objective = 'candidate_quality'),
            model_id UUID NOT NULL REFERENCES recommendation_model_versions(model_id),
            promotion_report JSONB NOT NULL,
            activation_reason TEXT NOT NULL,
            activated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE UNIQUE INDEX uq_recommendation_live_deployment_model
            ON recommendation_live_deployments(model_id);

        CREATE TABLE recommendation_live_deployment_events (
            event_id UUID PRIMARY KEY,
            objective TEXT NOT NULL CHECK (objective = 'candidate_quality'),
            model_id UUID REFERENCES recommendation_model_versions(model_id),
            event_type TEXT NOT NULL CHECK (
                event_type IN ('ACTIVATED', 'ROLLED_BACK', 'BLOCKED')
            ),
            reason TEXT NOT NULL,
            details JSONB NOT NULL DEFAULT '{}'::jsonb,
            occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE INDEX idx_recommendation_live_deployment_events
            ON recommendation_live_deployment_events(objective, occurred_at DESC);

        CREATE TABLE recommendation_live_observations (
            observation_id UUID PRIMARY KEY,
            live_run_id UUID NOT NULL,
            candidate_id UUID NOT NULL,
            candidate_version BIGINT NOT NULL,
            strategy_id TEXT NOT NULL,
            baseline_rank INTEGER NOT NULL CHECK (baseline_rank >= 1),
            live_rank INTEGER NOT NULL CHECK (live_rank >= 1),
            model_id UUID NOT NULL REFERENCES recommendation_model_versions(model_id),
            candidate_quality_score DOUBLE PRECISION NOT NULL CHECK (
                candidate_quality_score >= 0.0 AND candidate_quality_score <= 1.0
            ),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            FOREIGN KEY (candidate_id, candidate_version)
                REFERENCES recommended_class_candidate_versions(candidate_id, candidate_version)
                ON DELETE CASCADE
        );

        CREATE UNIQUE INDEX uq_recommendation_live_run_candidate
            ON recommendation_live_observations(
                live_run_id, candidate_id, candidate_version
            );

        CREATE INDEX idx_recommendation_live_run
            ON recommendation_live_observations(live_run_id, live_rank);

        CREATE INDEX idx_recommendation_live_candidate
            ON recommendation_live_observations(
                candidate_id, candidate_version, created_at DESC
            );

        CREATE INDEX idx_recommendation_live_model
            ON recommendation_live_observations(model_id, created_at DESC);

        ALTER TABLE recommended_class_feedback
            ADD COLUMN live_observation_id UUID
            REFERENCES recommendation_live_observations(observation_id)
            ON DELETE SET NULL;

        CREATE INDEX idx_recommended_feedback_live_observation
            ON recommended_class_feedback(live_observation_id)
            WHERE live_observation_id IS NOT NULL;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX idx_recommended_feedback_live_observation;
        ALTER TABLE recommended_class_feedback DROP COLUMN live_observation_id;
        DROP TABLE recommendation_live_observations;
        DROP TABLE recommendation_live_deployment_events;
        DROP TABLE recommendation_live_deployments;
        DROP INDEX uq_recommendation_shadow_run_candidate;

        ALTER TABLE recommended_class_feedback
            DROP CONSTRAINT IF EXISTS recommended_class_feedback_shadow_observation_id_fkey;
        ALTER TABLE recommended_class_feedback
            ADD CONSTRAINT recommended_class_feedback_shadow_observation_id_fkey
            FOREIGN KEY (shadow_observation_id)
            REFERENCES recommendation_shadow_observations(observation_id);
        """
    )
