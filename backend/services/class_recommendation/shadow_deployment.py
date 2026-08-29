"""Explicitly activate or deactivate offline-approved models for shadow scoring.

Offline approval remains a model-governance state with no ranking effect. Shadow
activation is a separate audited deployment decision. Even an active shadow deployment
never changes the baseline HDBSCAN/centroid ordering.
"""

from __future__ import annotations

import uuid

from services.database.postgres import postgres_client

OBJECTIVES = frozenset({"membership", "candidate_quality"})


def shadow_activation_allowed(model: dict) -> tuple[bool, str | None]:
    objective = str(model.get("objective") or "")
    if objective not in OBJECTIVES:
        return False, "Unknown recommendation model objective"
    if model.get("status") != "OFFLINE_APPROVED":
        return False, "Only OFFLINE_APPROVED models can enter shadow mode"
    return True, None


class RecommendationShadowDeploymentRegistry:
    def __init__(self, database=postgres_client) -> None:
        self.database = database

    def activate(self, *, model_id: str, reason: str) -> dict:
        reason = reason.strip()
        if not reason:
            raise ValueError("Shadow activation requires a non-empty reason")

        with self.database.transaction() as conn:
            model = conn.execute(
                """
                SELECT model_id::text AS model_id, objective, model_version, status
                FROM recommendation_model_versions
                WHERE model_id = %s
                FOR UPDATE
                """,
                (model_id,),
            ).fetchone()
            if model is None:
                raise LookupError("Recommendation model was not found")

            allowed, denial = shadow_activation_allowed(model)
            if not allowed:
                raise ValueError(denial or "Model cannot enter shadow mode")

            objective = str(model["objective"])
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                (f"recommendation-shadow:{objective}",),
            )
            current = conn.execute(
                """
                SELECT objective, model_id::text AS model_id
                FROM recommendation_shadow_deployments
                WHERE objective = %s
                FOR UPDATE
                """,
                (objective,),
            ).fetchone()
            if current is not None and str(current["model_id"]) == str(model_id):
                return {
                    "objective": objective,
                    "model_id": str(model_id),
                    "model_version": int(model["model_version"]),
                    "state": "SHADOW_ACTIVE",
                    "changed": False,
                    "ranking_effect": "none",
                }

            if current is not None:
                previous_model_id = str(current["model_id"])
                conn.execute(
                    "DELETE FROM recommendation_shadow_deployments WHERE objective = %s",
                    (objective,),
                )
                self._event(
                    conn,
                    objective=objective,
                    model_id=previous_model_id,
                    event_type="DEACTIVATED",
                    reason=f"Superseded by shadow model {model_id}",
                )

            conn.execute(
                """
                INSERT INTO recommendation_shadow_deployments(
                    objective, model_id, activation_reason
                ) VALUES (%s, %s, %s)
                """,
                (objective, model_id, reason),
            )
            self._event(
                conn,
                objective=objective,
                model_id=model_id,
                event_type="ACTIVATED",
                reason=reason,
            )
            return {
                "objective": objective,
                "model_id": str(model_id),
                "model_version": int(model["model_version"]),
                "state": "SHADOW_ACTIVE",
                "changed": True,
                "ranking_effect": "none",
            }

    def deactivate(self, *, objective: str, reason: str) -> dict:
        if objective not in OBJECTIVES:
            raise ValueError("Unknown recommendation model objective")
        reason = reason.strip()
        if not reason:
            raise ValueError("Shadow deactivation requires a non-empty reason")

        with self.database.transaction() as conn:
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                (f"recommendation-shadow:{objective}",),
            )
            current = conn.execute(
                """
                SELECT objective, model_id::text AS model_id
                FROM recommendation_shadow_deployments
                WHERE objective = %s
                FOR UPDATE
                """,
                (objective,),
            ).fetchone()
            if current is None:
                return {
                    "objective": objective,
                    "state": "SHADOW_INACTIVE",
                    "changed": False,
                    "ranking_effect": "none",
                }

            model_id = str(current["model_id"])
            conn.execute(
                "DELETE FROM recommendation_shadow_deployments WHERE objective = %s",
                (objective,),
            )
            self._event(
                conn,
                objective=objective,
                model_id=model_id,
                event_type="DEACTIVATED",
                reason=reason,
            )
            return {
                "objective": objective,
                "model_id": model_id,
                "state": "SHADOW_INACTIVE",
                "changed": True,
                "ranking_effect": "none",
            }

    def status(self) -> list[dict]:
        rows = self.database.fetch_all(
            """
            SELECT d.objective, d.model_id::text AS model_id,
                   m.model_version, m.feature_contract_version,
                   m.status AS model_status, d.activation_reason, d.activated_at
            FROM recommendation_shadow_deployments d
            JOIN recommendation_model_versions m ON m.model_id = d.model_id
            ORDER BY d.objective
            """
        )
        return [
            {
                **dict(row),
                "state": (
                    "SHADOW_ACTIVE"
                    if row["model_status"] == "OFFLINE_APPROVED"
                    else "SHADOW_BLOCKED"
                ),
                "ranking_effect": "none",
            }
            for row in rows
        ]

    @staticmethod
    def _event(
        conn,
        *,
        objective: str,
        model_id: str,
        event_type: str,
        reason: str,
    ) -> None:
        conn.execute(
            """
            INSERT INTO recommendation_shadow_deployment_events(
                event_id, objective, model_id, event_type, reason
            ) VALUES (%s, %s, %s, %s, %s)
            """,
            (str(uuid.uuid4()), objective, model_id, event_type, reason),
        )


recommendation_shadow_deployments = RecommendationShadowDeploymentRegistry()
