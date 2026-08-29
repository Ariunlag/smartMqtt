"""Score approved recommendation models in shadow mode without changing ranking.

Shadow scoring is observational only. The baseline HDBSCAN/centroid rank remains the
user-facing order. Learned probabilities are computed from the exact persisted candidate
version, returned as diagnostics, and recorded for later comparison with explicit user
feedback.
"""

from __future__ import annotations

import json
import logging
import math
import uuid
from typing import Any

from services.database.postgres import postgres_client

from .candidate_feedback import recommended_candidate_store
from .learning import (
    CANDIDATE_QUALITY_FEATURES,
    FEATURE_CONTRACT_VERSION,
    MEMBERSHIP_FEATURES,
    RecommendationFeedbackDatasetBuilder,
)
from .model_registry import ARTIFACT_FORMAT_VERSION, MODEL_TYPE

logger = logging.getLogger(__name__)


class ShadowArtifactError(ValueError):
    """Raised when a persisted model artifact is incompatible with shadow inference."""


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _expected_features(objective: str) -> tuple[str, ...]:
    if objective == "membership":
        return MEMBERSHIP_FEATURES
    if objective == "candidate_quality":
        return CANDIDATE_QUALITY_FEATURES
    raise ShadowArtifactError(f"Unknown shadow model objective: {objective}")


def score_model_artifact(model_row: dict, features: tuple[float, ...]) -> float:
    """Apply the portable StandardScaler + LogisticRegression JSON artifact."""
    objective = str(model_row["objective"])
    artifact = model_row.get("artifact") or {}
    expected_features = _expected_features(objective)

    if artifact.get("artifact_format_version") != ARTIFACT_FORMAT_VERSION:
        raise ShadowArtifactError("Unsupported recommendation model artifact format")
    if artifact.get("model_type") != MODEL_TYPE:
        raise ShadowArtifactError("Unsupported recommendation model type")
    if artifact.get("objective") != objective:
        raise ShadowArtifactError("Model artifact objective does not match registry row")
    if artifact.get("feature_contract_version") != FEATURE_CONTRACT_VERSION[objective]:
        raise ShadowArtifactError("Model feature contract is incompatible with runtime")
    if tuple(artifact.get("feature_names") or ()) != expected_features:
        raise ShadowArtifactError("Model feature names are incompatible with runtime")
    if len(features) != len(expected_features):
        raise ShadowArtifactError("Runtime feature vector has the wrong length")

    preprocessing = artifact.get("preprocessing") or {}
    estimator = artifact.get("estimator") or {}
    if preprocessing.get("type") != "standard_scaler":
        raise ShadowArtifactError("Unsupported recommendation preprocessing")
    if estimator.get("type") != "logistic_regression":
        raise ShadowArtifactError("Unsupported recommendation estimator")
    if list(estimator.get("classes") or ()) != [0, 1]:
        raise ShadowArtifactError("Binary recommendation model classes must be [0, 1]")

    means = tuple(float(value) for value in preprocessing.get("mean") or ())
    scales = tuple(float(value) for value in preprocessing.get("scale") or ())
    coefficients = tuple(float(value) for value in estimator.get("coefficients") or ())
    if not (
        len(means)
        == len(scales)
        == len(coefficients)
        == len(expected_features)
    ):
        raise ShadowArtifactError("Recommendation model parameter dimensions are invalid")
    if any(scale == 0.0 for scale in scales):
        raise ShadowArtifactError("Recommendation model scaler contains a zero scale")

    standardized = tuple(
        (float(value) - mean) / scale
        for value, mean, scale in zip(features, means, scales, strict=True)
    )
    logit = float(estimator.get("intercept", 0.0)) + sum(
        coefficient * value
        for coefficient, value in zip(coefficients, standardized, strict=True)
    )
    if logit >= 0.0:
        probability = 1.0 / (1.0 + math.exp(-logit))
    else:
        exp_value = math.exp(logit)
        probability = exp_value / (1.0 + exp_value)
    return float(probability)


class RecommendationShadowScorer:
    """Evaluate OFFLINE_APPROVED models beside the unchanged baseline ranking."""

    def __init__(
        self,
        database=postgres_client,
        candidate_store=recommended_candidate_store,
    ) -> None:
        self.database = database
        self.candidate_store = candidate_store

    def evaluate(self, candidate_set) -> dict:
        membership_model = self._approved_model("membership")
        quality_model = self._approved_model("candidate_quality")
        models = {
            "membership": self._model_summary(membership_model),
            "candidate_quality": self._model_summary(quality_model),
        }
        if membership_model is None and quality_model is None:
            return {
                "mode": "shadow",
                "status": "unavailable",
                "reason": "no_offline_approved_models",
                "ranking_effect": "none",
                "baseline_order_preserved": True,
                "models": models,
                "candidates": [],
            }

        shadow_run_id = str(uuid.uuid4())
        candidate_results = []
        observation_rows = []
        run_had_error = False

        for candidate in candidate_set.candidates:
            snapshot = self.candidate_store.get_snapshot(
                candidate.candidate_id,
                candidate.candidate_version,
            )
            if snapshot is None:
                run_had_error = True
                candidate_results.append(
                    {
                        "candidate_id": candidate.candidate_id,
                        "candidate_version": candidate.candidate_version,
                        "baseline_rank": candidate.rank,
                        "status": "error",
                        "reason": "candidate_snapshot_missing",
                        "candidate_quality_score": None,
                        "membership_scores": {},
                    }
                )
                continue

            feedback_snapshot = self._feedback_snapshot(snapshot)
            membership_scores: dict[str, dict[str, float | str | None]] = {}
            candidate_errors = []

            if membership_model is not None:
                for topic in candidate.member_topics:
                    row = {
                        "feedback_id": "shadow",
                        "candidate_id": candidate.candidate_id,
                        "candidate_version": candidate.candidate_version,
                        "action_type": "KEEP_TOPIC",
                        "topic": topic,
                        "evidence_snapshot": feedback_snapshot,
                    }
                    example, reason = RecommendationFeedbackDatasetBuilder._membership_example(
                        row
                    )
                    if example is None:
                        membership_scores[str(topic)] = {
                            "score": None,
                            "reason": reason or "membership_features_unavailable",
                        }
                        continue
                    try:
                        score = score_model_artifact(membership_model, example.features)
                    except ShadowArtifactError as exc:
                        candidate_errors.append(f"membership:{exc}")
                        membership_scores[str(topic)] = {
                            "score": None,
                            "reason": "model_incompatible",
                        }
                    else:
                        membership_scores[str(topic)] = {
                            "score": score,
                            "reason": None,
                        }

            quality_score = None
            if quality_model is not None:
                row = {
                    "feedback_id": "shadow",
                    "candidate_id": candidate.candidate_id,
                    "candidate_version": candidate.candidate_version,
                    "action_type": "ACCEPT_CANDIDATE",
                    "topic": None,
                    "evidence_snapshot": feedback_snapshot,
                }
                example, reason = (
                    RecommendationFeedbackDatasetBuilder._candidate_quality_example(row)
                )
                if example is None:
                    candidate_errors.append(
                        f"candidate_quality:{reason or 'features_unavailable'}"
                    )
                else:
                    try:
                        quality_score = score_model_artifact(
                            quality_model, example.features
                        )
                    except ShadowArtifactError as exc:
                        candidate_errors.append(f"candidate_quality:{exc}")

            status = "partial" if candidate_errors else "scored"
            if candidate_errors:
                run_had_error = True
            candidate_result = {
                "candidate_id": candidate.candidate_id,
                "candidate_version": candidate.candidate_version,
                "baseline_rank": candidate.rank,
                "status": status,
                "candidate_quality_score": quality_score,
                "membership_scores": membership_scores,
            }
            if candidate_errors:
                candidate_result["errors"] = candidate_errors
            candidate_results.append(candidate_result)

            observation_rows.append(
                {
                    "observation_id": str(uuid.uuid4()),
                    "shadow_run_id": shadow_run_id,
                    "candidate_id": candidate.candidate_id,
                    "candidate_version": candidate.candidate_version,
                    "strategy_id": candidate_set.strategy.strategy_id,
                    "baseline_rank": candidate.rank,
                    "membership_model_id": (
                        str(membership_model["model_id"])
                        if membership_model is not None
                        else None
                    ),
                    "candidate_quality_model_id": (
                        str(quality_model["model_id"])
                        if quality_model is not None
                        else None
                    ),
                    "membership_scores": membership_scores,
                    "candidate_quality_score": quality_score,
                    "scoring_status": "PARTIAL" if candidate_errors else "SCORED",
                }
            )

        persistence = self._persist_observations(observation_rows)
        if persistence["status"] != "stored":
            run_had_error = True

        both_models = membership_model is not None and quality_model is not None
        return {
            "mode": "shadow",
            "status": "scored" if both_models and not run_had_error else "partial",
            "ranking_effect": "none",
            "baseline_order_preserved": True,
            "shadow_run_id": shadow_run_id,
            "models": models,
            "persistence": persistence,
            "candidates": candidate_results,
        }

    def _approved_model(self, objective: str) -> dict | None:
        return self.database.fetch_one(
            """
            SELECT model_id::text AS model_id, objective, model_version,
                   feature_contract_version, artifact
            FROM recommendation_model_versions
            WHERE objective = %s AND status = 'OFFLINE_APPROVED'
            """,
            (objective,),
        )

    @staticmethod
    def _model_summary(model: dict | None) -> dict | None:
        if model is None:
            return None
        return {
            "model_id": str(model["model_id"]),
            "model_version": int(model["model_version"]),
            "feature_contract_version": str(model["feature_contract_version"]),
        }

    @staticmethod
    def _feedback_snapshot(snapshot: dict) -> dict:
        return {
            "candidate_id": str(snapshot["candidate_id"]),
            "candidate_version": int(snapshot["candidate_version"]),
            "strategy_id": str(snapshot["strategy_id"]),
            "member_topics": list(snapshot["member_topics"]),
            "discovery_evidence": list(snapshot["discovery_evidence"]),
            "snapshot_fingerprint": str(snapshot["snapshot_fingerprint"]),
            "candidate_evidence": snapshot["evidence_snapshot"],
        }

    def _persist_observations(self, rows: list[dict]) -> dict:
        if not rows:
            return {"status": "not_applicable", "count": 0}
        try:
            with self.database.transaction() as conn:
                for row in rows:
                    conn.execute(
                        """
                        INSERT INTO recommendation_shadow_observations(
                            observation_id, shadow_run_id, candidate_id,
                            candidate_version, strategy_id, baseline_rank,
                            membership_model_id, candidate_quality_model_id,
                            membership_scores, candidate_quality_score, scoring_status
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s,
                            %s, %s, %s::jsonb, %s, %s
                        )
                        """,
                        (
                            row["observation_id"],
                            row["shadow_run_id"],
                            row["candidate_id"],
                            row["candidate_version"],
                            row["strategy_id"],
                            row["baseline_rank"],
                            row["membership_model_id"],
                            row["candidate_quality_model_id"],
                            _canonical_json(row["membership_scores"]),
                            row["candidate_quality_score"],
                            row["scoring_status"],
                        ),
                    )
        except Exception:  # shadow persistence must never break baseline recommendations
            logger.exception("Failed to persist recommendation shadow observations")
            return {"status": "error", "count": 0}
        return {"status": "stored", "count": len(rows)}


recommendation_shadow_scorer = RecommendationShadowScorer()
