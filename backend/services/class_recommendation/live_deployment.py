"""Explicit live deployment and rollback for learned candidate-quality ranking.

Live ranking is intentionally narrower than the learning objectives. Version 1 may only
reorder already-generated recommendation candidates with the candidate-quality model.
It never creates candidates, changes candidate membership, mutates embeddings, or turns
unshown candidates into negative labels.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from typing import Any

from services.database.postgres import postgres_client

from .shadow_evaluation import build_shadow_evaluation_report

LIVE_OBJECTIVE = "candidate_quality"
LIVE_GATE_POLICY_VERSION = "live-shadow-gate-v1"


@dataclass(frozen=True, slots=True)
class LivePromotionGateConfig:
    min_samples: int = 20
    min_positive: int = 5
    min_negative: int = 5
    min_unique_candidates: int = 10
    min_balanced_accuracy: float = 0.60
    min_roc_auc: float = 0.60
    min_pairwise_comparisons: int = 10
    min_pairwise_accuracy_delta: float = 0.0

    def __post_init__(self) -> None:
        for name in (
            "min_samples",
            "min_positive",
            "min_negative",
            "min_unique_candidates",
            "min_pairwise_comparisons",
        ):
            if int(getattr(self, name)) < 1:
                raise ValueError(f"{name} must be at least 1")
        for name in ("min_balanced_accuracy", "min_roc_auc"):
            value = float(getattr(self, name))
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")
        if not -1.0 <= float(self.min_pairwise_accuracy_delta) <= 1.0:
            raise ValueError("min_pairwise_accuracy_delta must be between -1 and 1")


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    )


def _model_report(shadow_report: dict, model_id: str) -> dict | None:
    for report in (shadow_report.get("candidate_quality") or {}).get("models") or ():
        if str(report.get("model_id")) == str(model_id):
            return report
    return None


def build_live_promotion_report(
    database=postgres_client,
    *,
    model_id: str,
    config: LivePromotionGateConfig | None = None,
) -> dict:
    """Gate live ranking using real, explicit shadow feedback for one exact model."""
    policy = config or LivePromotionGateConfig()
    model = database.fetch_one(
        """
        SELECT model_id::text AS model_id, objective, model_version,
               feature_contract_version, status
        FROM recommendation_model_versions
        WHERE model_id = %s
        """,
        (model_id,),
    )
    if model is None:
        raise LookupError("Recommendation model was not found")

    shadow_report = build_shadow_evaluation_report(
        database,
        include_fixture_feedback=False,
    )
    evaluation = _model_report(shadow_report, model_id) or {}
    source = shadow_report.get("source") or {}
    source_policy = source.get("source_policy") or {}

    checks = [
        {
            "name": "candidate_quality_objective",
            "passed": model.get("objective") == LIVE_OBJECTIVE,
            "actual": model.get("objective"),
            "required": LIVE_OBJECTIVE,
        },
        {
            "name": "offline_approved",
            "passed": model.get("status") == "OFFLINE_APPROVED",
            "actual": model.get("status"),
            "required": "OFFLINE_APPROVED",
        },
        {
            "name": "fixture_feedback_excluded",
            "passed": source_policy.get("fixture_feedback") == "excluded_by_default",
            "actual": source_policy.get("fixture_feedback"),
            "required": "excluded_by_default",
        },
        {
            "name": "explicit_feedback_only",
            "passed": source.get("label_policy") == "explicit_feedback_only",
            "actual": source.get("label_policy"),
            "required": "explicit_feedback_only",
        },
        {
            "name": "unshown_candidates_not_negative",
            "passed": source.get("unshown_candidates_as_negative") is False,
            "actual": source.get("unshown_candidates_as_negative"),
            "required": False,
        },
        {
            "name": "shadow_evaluated",
            "passed": evaluation.get("status") == "evaluated",
            "actual": evaluation.get("status"),
            "required": "evaluated",
        },
        {
            "name": "same_run_pairwise_policy",
            "passed": evaluation.get("pairwise_grouping") == "same_shadow_run_only",
            "actual": evaluation.get("pairwise_grouping"),
            "required": "same_shadow_run_only",
        },
        {
            "name": "sample_count",
            "passed": int(evaluation.get("sample_count", 0)) >= policy.min_samples,
            "actual": int(evaluation.get("sample_count", 0)),
            "required": policy.min_samples,
        },
        {
            "name": "positive_count",
            "passed": int(evaluation.get("positive_count", 0)) >= policy.min_positive,
            "actual": int(evaluation.get("positive_count", 0)),
            "required": policy.min_positive,
        },
        {
            "name": "negative_count",
            "passed": int(evaluation.get("negative_count", 0)) >= policy.min_negative,
            "actual": int(evaluation.get("negative_count", 0)),
            "required": policy.min_negative,
        },
        {
            "name": "unique_candidate_count",
            "passed": int(evaluation.get("unique_candidate_count", 0))
            >= policy.min_unique_candidates,
            "actual": int(evaluation.get("unique_candidate_count", 0)),
            "required": policy.min_unique_candidates,
        },
        {
            "name": "balanced_accuracy",
            "passed": evaluation.get("status") == "evaluated"
            and float(evaluation.get("balanced_accuracy", -1.0))
            >= policy.min_balanced_accuracy,
            "actual": evaluation.get("balanced_accuracy"),
            "required": policy.min_balanced_accuracy,
        },
        {
            "name": "roc_auc",
            "passed": evaluation.get("status") == "evaluated"
            and float(evaluation.get("roc_auc", -1.0)) >= policy.min_roc_auc,
            "actual": evaluation.get("roc_auc"),
            "required": policy.min_roc_auc,
        },
        {
            "name": "pairwise_comparisons",
            "passed": int(evaluation.get("pairwise_comparison_count", 0))
            >= policy.min_pairwise_comparisons,
            "actual": int(evaluation.get("pairwise_comparison_count", 0)),
            "required": policy.min_pairwise_comparisons,
        },
        {
            "name": "pairwise_vs_baseline",
            "passed": evaluation.get("pairwise_accuracy_delta") is not None
            and float(evaluation["pairwise_accuracy_delta"])
            >= policy.min_pairwise_accuracy_delta,
            "actual": evaluation.get("pairwise_accuracy_delta"),
            "required": f">= {policy.min_pairwise_accuracy_delta}",
        },
    ]
    return {
        "passed": all(bool(check["passed"]) for check in checks),
        "policy": {
            "version": LIVE_GATE_POLICY_VERSION,
            **asdict(policy),
        },
        "model": {
            "model_id": str(model["model_id"]),
            "model_version": int(model["model_version"]),
            "objective": str(model["objective"]),
            "feature_contract_version": str(model["feature_contract_version"]),
            "status": str(model["status"]),
        },
        "shadow_evaluation": evaluation or None,
        "source_policy": source_policy,
        "checks": checks,
        "ranking_policy": "candidate_quality_desc_then_baseline_rank",
        "membership_effect": "none",
    }


class RecommendationLiveDeploymentRegistry:
    def __init__(self, database=postgres_client) -> None:
        self.database = database

    def check(
        self,
        *,
        model_id: str,
        config: LivePromotionGateConfig | None = None,
    ) -> dict:
        return build_live_promotion_report(
            self.database,
            model_id=model_id,
            config=config,
        )

    def activate(
        self,
        *,
        model_id: str,
        reason: str,
        config: LivePromotionGateConfig | None = None,
    ) -> dict:
        reason = reason.strip()
        if not reason:
            raise ValueError("Live activation requires a non-empty reason")

        report = self.check(model_id=model_id, config=config)
        if not report["passed"]:
            with self.database.transaction() as conn:
                self._event(
                    conn,
                    model_id=model_id,
                    event_type="BLOCKED",
                    reason=reason,
                    details={"promotion_report": report},
                )
            raise ValueError("Live promotion gate did not pass")

        with self.database.transaction() as conn:
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                ("recommendation-live:candidate_quality",),
            )
            current = conn.execute(
                """
                SELECT model_id::text AS model_id
                FROM recommendation_live_deployments
                WHERE objective = 'candidate_quality'
                FOR UPDATE
                """
            ).fetchone()
            if current is not None and str(current["model_id"]) == str(model_id):
                return {
                    "objective": LIVE_OBJECTIVE,
                    "model_id": str(model_id),
                    "state": "LIVE_ACTIVE",
                    "changed": False,
                    "ranking_effect": "candidate_reorder",
                    "membership_effect": "none",
                    "promotion_report": report,
                }

            if current is not None:
                previous_model_id = str(current["model_id"])
                conn.execute(
                    "DELETE FROM recommendation_live_deployments WHERE objective = 'candidate_quality'"
                )
                self._event(
                    conn,
                    model_id=previous_model_id,
                    event_type="ROLLED_BACK",
                    reason=f"Superseded by live model {model_id}",
                    details={"replacement_model_id": str(model_id)},
                )

            conn.execute(
                """
                INSERT INTO recommendation_live_deployments(
                    objective, model_id, promotion_report, activation_reason
                ) VALUES ('candidate_quality', %s, %s::jsonb, %s)
                """,
                (model_id, _canonical_json(report), reason),
            )
            self._event(
                conn,
                model_id=model_id,
                event_type="ACTIVATED",
                reason=reason,
                details={"promotion_report": report},
            )
            return {
                "objective": LIVE_OBJECTIVE,
                "model_id": str(model_id),
                "model_version": int(report["model"]["model_version"]),
                "state": "LIVE_ACTIVE",
                "changed": True,
                "ranking_effect": "candidate_reorder",
                "membership_effect": "none",
                "promotion_report": report,
            }

    def rollback(self, *, reason: str) -> dict:
        reason = reason.strip()
        if not reason:
            raise ValueError("Live rollback requires a non-empty reason")

        with self.database.transaction() as conn:
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                ("recommendation-live:candidate_quality",),
            )
            current = conn.execute(
                """
                SELECT model_id::text AS model_id
                FROM recommendation_live_deployments
                WHERE objective = 'candidate_quality'
                FOR UPDATE
                """
            ).fetchone()
            if current is None:
                return {
                    "objective": LIVE_OBJECTIVE,
                    "state": "BASELINE_ACTIVE",
                    "changed": False,
                    "ranking_effect": "baseline",
                }

            model_id = str(current["model_id"])
            conn.execute(
                "DELETE FROM recommendation_live_deployments WHERE objective = 'candidate_quality'"
            )
            self._event(
                conn,
                model_id=model_id,
                event_type="ROLLED_BACK",
                reason=reason,
                details={"ranking_effect": "baseline"},
            )
            return {
                "objective": LIVE_OBJECTIVE,
                "model_id": model_id,
                "state": "BASELINE_ACTIVE",
                "changed": True,
                "ranking_effect": "baseline",
            }

    def status(self) -> list[dict]:
        rows = self.database.fetch_all(
            """
            SELECT d.objective, d.model_id::text AS model_id,
                   m.model_version, m.feature_contract_version,
                   m.status AS model_status, d.activation_reason,
                   d.promotion_report, d.activated_at
            FROM recommendation_live_deployments d
            JOIN recommendation_model_versions m ON m.model_id = d.model_id
            ORDER BY d.objective
            """
        )
        return [
            {
                **dict(row),
                "state": (
                    "LIVE_ACTIVE"
                    if row["model_status"] == "OFFLINE_APPROVED"
                    else "LIVE_BLOCKED"
                ),
                "ranking_effect": (
                    "candidate_reorder"
                    if row["model_status"] == "OFFLINE_APPROVED"
                    else "baseline_fallback"
                ),
                "membership_effect": "none",
            }
            for row in rows
        ]

    @staticmethod
    def _event(
        conn,
        *,
        model_id: str | None,
        event_type: str,
        reason: str,
        details: dict | None = None,
    ) -> None:
        conn.execute(
            """
            INSERT INTO recommendation_live_deployment_events(
                event_id, objective, model_id, event_type, reason, details
            ) VALUES (%s, 'candidate_quality', %s, %s, %s, %s::jsonb)
            """,
            (
                str(uuid.uuid4()),
                model_id,
                event_type,
                reason,
                _canonical_json(details or {}),
            ),
        )


recommendation_live_deployments = RecommendationLiveDeploymentRegistry()
