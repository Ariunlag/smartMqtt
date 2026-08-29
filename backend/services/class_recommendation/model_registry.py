"""Version, evaluate, and explicitly approve offline recommendation models.

The registry is deliberately separate from live recommendation ranking. Registering or
approving a model records reproducible offline state only; no runtime scorer consumes
these rows yet.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass
from typing import Any

from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from services.database.postgres import postgres_client

from .learning import (
    FEATURE_CONTRACT_VERSION,
    RecommendationFeedbackDatasetBuilder,
    TrainingDataset,
    train_offline_report,
)

MODEL_TYPE = "standard_scaler+logistic_regression"
ARTIFACT_FORMAT_VERSION = "recommendation-logistic-json-v1"
GATE_POLICY_VERSION = "offline-gate-v1"


@dataclass(frozen=True, slots=True)
class EvaluationGateConfig:
    """Conservative prototype gate; thresholds are policy, not model features."""

    min_samples: int = 20
    min_positive: int = 5
    min_negative: int = 5
    min_evaluation_groups: int = 4
    min_balanced_accuracy: float = 0.60
    min_roc_auc: float = 0.60

    def __post_init__(self) -> None:
        for name in (
            "min_samples",
            "min_positive",
            "min_negative",
            "min_evaluation_groups",
        ):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} must be at least 1")
        for name in ("min_balanced_accuracy", "min_roc_auc"):
            value = float(getattr(self, name))
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    )


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def dataset_fingerprint(dataset: TrainingDataset) -> str:
    """Fingerprint semantic training content without overcounting repeated clicks."""
    rows = [
        {
            "candidate_id": example.candidate_id,
            "candidate_version": example.candidate_version,
            "strategy_id": example.strategy_id,
            "target": example.target,
            "label": example.label,
            "features": list(example.features),
            "evaluation_group": example.evaluation_group,
        }
        for example in dataset.examples
    ]
    rows.sort(
        key=lambda row: (
            row["candidate_id"],
            row["candidate_version"],
            row["target"],
            row["label"],
        )
    )
    return _sha256(
        {
            "objective": dataset.objective,
            "feature_contract_version": FEATURE_CONTRACT_VERSION[dataset.objective],
            "feature_names": list(dataset.feature_names),
            "source_policy": {
                "include_fixture_feedback": dataset.include_fixture_feedback,
                "excluded_topic_prefixes": list(dataset.excluded_topic_prefixes),
            },
            "examples": rows,
        }
    )


def build_model_artifact(dataset: TrainingDataset) -> dict:
    """Fit the baseline and serialize inference state as portable JSON, not pickle."""
    report = train_offline_report(dataset)
    if report["status"] != "trained_offline":
        raise ValueError("Dataset is not trainable")

    model = Pipeline(
        steps=(
            ("scale", StandardScaler()),
            (
                "logistic_regression",
                LogisticRegression(max_iter=2000, solver="liblinear", random_state=42),
            ),
        )
    )
    model.fit(dataset.matrix, dataset.labels)
    scaler: StandardScaler = model.named_steps["scale"]
    estimator: LogisticRegression = model.named_steps["logistic_regression"]

    return {
        "artifact_format_version": ARTIFACT_FORMAT_VERSION,
        "model_type": MODEL_TYPE,
        "objective": dataset.objective,
        "feature_contract_version": FEATURE_CONTRACT_VERSION[dataset.objective],
        "feature_names": list(dataset.feature_names),
        "dataset_fingerprint": dataset_fingerprint(dataset),
        "source_feedback_ids": sorted(example.feedback_id for example in dataset.examples),
        "preprocessing": {
            "type": "standard_scaler",
            "mean": [float(value) for value in scaler.mean_],
            "scale": [float(value) for value in scaler.scale_],
            "variance": [float(value) for value in scaler.var_],
        },
        "estimator": {
            "type": "logistic_regression",
            "classes": [int(value) for value in estimator.classes_],
            "coefficients": [float(value) for value in estimator.coef_[0]],
            "intercept": float(estimator.intercept_[0]),
            "solver": estimator.solver,
            "max_iter": int(estimator.max_iter),
            "random_state": estimator.random_state,
        },
    }


def evaluate_offline_gate(
    training_report: dict,
    config: EvaluationGateConfig | None = None,
) -> dict:
    """Evaluate reproducible readiness checks; never auto-promote a model."""
    policy = config or EvaluationGateConfig()
    source_policy = training_report.get("source_policy") or {}
    cv = training_report.get("cross_validation") or {}

    checks = [
        {
            "name": "trained_offline",
            "passed": training_report.get("status") == "trained_offline",
            "actual": training_report.get("status"),
            "required": "trained_offline",
        },
        {
            "name": "fixture_feedback_excluded",
            "passed": source_policy.get("fixture_feedback") == "excluded_by_default",
            "actual": source_policy.get("fixture_feedback"),
            "required": "excluded_by_default",
        },
        {
            "name": "sample_count",
            "passed": int(training_report.get("sample_count", 0)) >= policy.min_samples,
            "actual": int(training_report.get("sample_count", 0)),
            "required": policy.min_samples,
        },
        {
            "name": "positive_count",
            "passed": int(training_report.get("positive_count", 0)) >= policy.min_positive,
            "actual": int(training_report.get("positive_count", 0)),
            "required": policy.min_positive,
        },
        {
            "name": "negative_count",
            "passed": int(training_report.get("negative_count", 0)) >= policy.min_negative,
            "actual": int(training_report.get("negative_count", 0)),
            "required": policy.min_negative,
        },
        {
            "name": "evaluation_groups",
            "passed": int(training_report.get("unique_evaluation_group_count", 0))
            >= policy.min_evaluation_groups,
            "actual": int(training_report.get("unique_evaluation_group_count", 0)),
            "required": policy.min_evaluation_groups,
        },
        {
            "name": "grouped_cross_validation",
            "passed": cv.get("status") == "available",
            "actual": cv.get("status"),
            "required": "available",
        },
        {
            "name": "balanced_accuracy",
            "passed": cv.get("status") == "available"
            and float(cv.get("balanced_accuracy", -1.0)) >= policy.min_balanced_accuracy,
            "actual": cv.get("balanced_accuracy"),
            "required": policy.min_balanced_accuracy,
        },
        {
            "name": "roc_auc",
            "passed": cv.get("status") == "available"
            and float(cv.get("roc_auc", -1.0)) >= policy.min_roc_auc,
            "actual": cv.get("roc_auc"),
            "required": policy.min_roc_auc,
        },
    ]
    gate_policy = {
        "version": GATE_POLICY_VERSION,
        **asdict(policy),
    }
    return {
        "passed": all(check["passed"] for check in checks),
        "policy": gate_policy,
        "policy_fingerprint": _sha256(gate_policy),
        "checks": checks,
        "note": "Passing this gate permits OFFLINE_APPROVED only; live ranking remains disconnected.",
    }


def approval_allowed(model_row: dict, evaluation_row: dict) -> tuple[bool, str | None]:
    if model_row.get("status") == "RETIRED":
        return False, "Retired models cannot be approved"
    gate = evaluation_row.get("gate_report") or {}
    if not gate.get("passed"):
        return False, "Offline evaluation gate has not passed"
    if str(evaluation_row.get("model_id")) != str(model_row.get("model_id")):
        return False, "Evaluation does not belong to this model"
    return True, None


class RecommendationModelRegistry:
    def __init__(self, database=postgres_client) -> None:
        self.database = database

    def register_dataset(
        self,
        dataset: TrainingDataset,
        *,
        gate_config: EvaluationGateConfig | None = None,
    ) -> dict:
        training_report = train_offline_report(dataset)
        if training_report["status"] != "trained_offline":
            return {
                "registered": False,
                "objective": dataset.objective,
                "reason": training_report.get("reason", "dataset is not trainable"),
                "training_report": training_report,
            }

        fingerprint = dataset_fingerprint(dataset)
        artifact = build_model_artifact(dataset)
        gate_report = evaluate_offline_gate(training_report, gate_config)
        feature_contract = FEATURE_CONTRACT_VERSION[dataset.objective]

        with self.database.transaction() as conn:
            existing = conn.execute(
                """
                SELECT model_id::text AS model_id, model_version, status
                FROM recommendation_model_versions
                WHERE objective = %s
                  AND feature_contract_version = %s
                  AND dataset_fingerprint = %s
                  AND model_type = %s
                """,
                (dataset.objective, feature_contract, fingerprint, MODEL_TYPE),
            ).fetchone()

            if existing is None:
                conn.execute(
                    "SELECT pg_advisory_xact_lock(hashtext(%s))",
                    (f"recommendation-model:{dataset.objective}",),
                )
                version_row = conn.execute(
                    """
                    SELECT COALESCE(MAX(model_version), 0) + 1 AS next_version
                    FROM recommendation_model_versions
                    WHERE objective = %s
                    """,
                    (dataset.objective,),
                ).fetchone()
                model_version = int(version_row["next_version"])
                model_id = str(uuid.uuid4())
                conn.execute(
                    """
                    INSERT INTO recommendation_model_versions(
                        model_id, objective, model_version, feature_contract_version,
                        dataset_fingerprint, model_type, artifact, training_report
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)
                    """,
                    (
                        model_id,
                        dataset.objective,
                        model_version,
                        feature_contract,
                        fingerprint,
                        MODEL_TYPE,
                        _canonical_json(artifact),
                        _canonical_json(training_report),
                    ),
                )
                self._event(
                    conn,
                    model_id=model_id,
                    event_type="REGISTERED",
                    details={
                        "model_version": model_version,
                        "dataset_fingerprint": fingerprint,
                        "feature_contract_version": feature_contract,
                    },
                )
                registered = True
                status = "CANDIDATE"
            else:
                model_id = str(existing["model_id"])
                model_version = int(existing["model_version"])
                status = str(existing["status"])
                registered = False

            evaluation = self._persist_evaluation(
                conn,
                model_id=model_id,
                gate_report=gate_report,
            )

        return {
            "registered": registered,
            "objective": dataset.objective,
            "model_id": model_id,
            "model_version": model_version,
            "status": status,
            "dataset_fingerprint": fingerprint,
            "feature_contract_version": feature_contract,
            "evaluation": evaluation,
            "training_report": training_report,
        }

    def register_from_feedback(
        self,
        *,
        include_fixture_feedback: bool = False,
        gate_config: EvaluationGateConfig | None = None,
    ) -> dict:
        datasets = RecommendationFeedbackDatasetBuilder(
            self.database,
            include_fixture_feedback=include_fixture_feedback,
        ).build()
        return {
            objective: self.register_dataset(dataset, gate_config=gate_config)
            for objective, dataset in datasets.items()
        }

    def _persist_evaluation(self, conn, *, model_id: str, gate_report: dict) -> dict:
        policy = gate_report["policy"]
        policy_fingerprint = str(gate_report["policy_fingerprint"])
        existing = conn.execute(
            """
            SELECT evaluation_id::text AS evaluation_id, evaluated_at
            FROM recommendation_model_evaluations
            WHERE model_id = %s AND gate_policy_fingerprint = %s
            """,
            (model_id, policy_fingerprint),
        ).fetchone()
        if existing is not None:
            return {
                "evaluation_id": str(existing["evaluation_id"]),
                "gate_report": gate_report,
                "existing": True,
            }

        evaluation_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO recommendation_model_evaluations(
                evaluation_id, model_id, gate_policy_version,
                gate_policy_fingerprint, gate_report
            ) VALUES (%s, %s, %s, %s, %s::jsonb)
            """,
            (
                evaluation_id,
                model_id,
                str(policy["version"]),
                policy_fingerprint,
                _canonical_json(gate_report),
            ),
        )
        self._event(
            conn,
            model_id=model_id,
            event_type="EVALUATED",
            details={
                "evaluation_id": evaluation_id,
                "gate_policy_version": policy["version"],
                "gate_policy_fingerprint": policy_fingerprint,
                "passed": bool(gate_report["passed"]),
            },
        )
        return {
            "evaluation_id": evaluation_id,
            "gate_report": gate_report,
            "existing": False,
        }

    def approve_offline(
        self,
        *,
        model_id: str,
        evaluation_id: str,
        reason: str,
    ) -> dict:
        if not reason.strip():
            raise ValueError("Offline approval requires a non-empty reason")

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

            evaluation = conn.execute(
                """
                SELECT evaluation_id::text AS evaluation_id,
                       model_id::text AS model_id, gate_report
                FROM recommendation_model_evaluations
                WHERE evaluation_id = %s
                """,
                (evaluation_id,),
            ).fetchone()
            if evaluation is None:
                raise LookupError("Recommendation model evaluation was not found")

            allowed, denial = approval_allowed(model, evaluation)
            if not allowed:
                raise ValueError(denial or "Model is not eligible for offline approval")

            if model["status"] == "OFFLINE_APPROVED":
                return {
                    "model_id": str(model["model_id"]),
                    "objective": model["objective"],
                    "model_version": int(model["model_version"]),
                    "status": "OFFLINE_APPROVED",
                    "changed": False,
                }

            previous = conn.execute(
                """
                SELECT model_id::text AS model_id, model_version
                FROM recommendation_model_versions
                WHERE objective = %s AND status = 'OFFLINE_APPROVED'
                FOR UPDATE
                """,
                (model["objective"],),
            ).fetchone()
            if previous is not None:
                conn.execute(
                    """
                    UPDATE recommendation_model_versions
                    SET status = 'RETIRED', retired_at = now()
                    WHERE model_id = %s
                    """,
                    (previous["model_id"],),
                )
                self._event(
                    conn,
                    model_id=str(previous["model_id"]),
                    event_type="RETIRED",
                    reason="Superseded by a newly approved offline model",
                    details={"replacement_model_id": str(model["model_id"])},
                )

            conn.execute(
                """
                UPDATE recommendation_model_versions
                SET status = 'OFFLINE_APPROVED', approved_at = now(), retired_at = NULL
                WHERE model_id = %s
                """,
                (model_id,),
            )
            self._event(
                conn,
                model_id=model_id,
                event_type="OFFLINE_APPROVED",
                reason=reason.strip(),
                details={
                    "evaluation_id": evaluation_id,
                    "runtime_effect": "none",
                },
            )
            return {
                "model_id": model_id,
                "objective": model["objective"],
                "model_version": int(model["model_version"]),
                "status": "OFFLINE_APPROVED",
                "changed": True,
            }

    def retire(self, *, model_id: str, reason: str) -> dict:
        if not reason.strip():
            raise ValueError("Retirement requires a non-empty reason")
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
            if model["status"] == "RETIRED":
                return {
                    "model_id": model_id,
                    "status": "RETIRED",
                    "changed": False,
                }
            conn.execute(
                """
                UPDATE recommendation_model_versions
                SET status = 'RETIRED', retired_at = now()
                WHERE model_id = %s
                """,
                (model_id,),
            )
            self._event(
                conn,
                model_id=model_id,
                event_type="RETIRED",
                reason=reason.strip(),
                details={"previous_status": str(model["status"])},
            )
            return {"model_id": model_id, "status": "RETIRED", "changed": True}

    def list_models(self, objective: str | None = None) -> list[dict]:
        sql = """
            SELECT model_id::text AS model_id, objective, model_version,
                   feature_contract_version, dataset_fingerprint, model_type,
                   status, created_at, approved_at, retired_at
            FROM recommendation_model_versions
        """
        params: tuple = ()
        if objective is not None:
            if objective not in {"membership", "candidate_quality"}:
                raise ValueError("Unknown recommendation model objective")
            sql += " WHERE objective = %s"
            params = (objective,)
        sql += " ORDER BY objective, model_version DESC"
        return self.database.fetch_all(sql, params)

    def get_model(self, model_id: str) -> dict | None:
        return self.database.fetch_one(
            """
            SELECT model_id::text AS model_id, objective, model_version,
                   feature_contract_version, dataset_fingerprint, model_type,
                   artifact, training_report, status,
                   created_at, approved_at, retired_at
            FROM recommendation_model_versions
            WHERE model_id = %s
            """,
            (model_id,),
        )

    def list_evaluations(self, model_id: str) -> list[dict]:
        return self.database.fetch_all(
            """
            SELECT evaluation_id::text AS evaluation_id,
                   model_id::text AS model_id, gate_policy_version,
                   gate_policy_fingerprint, gate_report, evaluated_at
            FROM recommendation_model_evaluations
            WHERE model_id = %s
            ORDER BY evaluated_at DESC
            """,
            (model_id,),
        )

    @staticmethod
    def _event(
        conn,
        *,
        model_id: str,
        event_type: str,
        reason: str | None = None,
        details: dict | None = None,
    ) -> None:
        conn.execute(
            """
            INSERT INTO recommendation_model_events(
                event_id, model_id, event_type, reason, details
            ) VALUES (%s, %s, %s, %s, %s::jsonb)
            """,
            (
                str(uuid.uuid4()),
                model_id,
                event_type,
                reason,
                _canonical_json(details or {}),
            ),
        )


recommendation_model_registry = RecommendationModelRegistry()
