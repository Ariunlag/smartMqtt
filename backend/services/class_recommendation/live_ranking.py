"""Apply an explicitly promoted candidate-quality model to live candidate ordering.

Candidate generation and membership remain owned by the selected HDBSCAN/centroid
strategy. This layer can only reorder the exact candidates that discovery already
produced. Any inference, feature, snapshot, or audit-persistence error falls back to the
unchanged baseline order for the entire request.
"""

from __future__ import annotations

import json
import logging
import uuid

from services.database.postgres import postgres_client

from .candidate_feedback import recommended_candidate_store
from .discovery import RecommendedClassCandidate, RecommendedClassCandidateSet
from .learning import RecommendationFeedbackDatasetBuilder
from .shadow import ShadowArtifactError, score_model_artifact

logger = logging.getLogger(__name__)


def _canonical_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


class RecommendationLiveRanker:
    def __init__(
        self,
        database=postgres_client,
        candidate_store=recommended_candidate_store,
    ) -> None:
        self.database = database
        self.candidate_store = candidate_store

    def apply(
        self,
        candidate_set: RecommendedClassCandidateSet,
    ) -> tuple[RecommendedClassCandidateSet, dict]:
        model = self._active_model()
        if model is None:
            return candidate_set, {
                "mode": "live",
                "status": "baseline",
                "reason": "no_live_candidate_quality_model",
                "ranking_effect": "baseline",
                "membership_effect": "none",
                "model": None,
            }
        if not candidate_set.candidates:
            return candidate_set, {
                "mode": "live",
                "status": "no_candidates",
                "ranking_effect": "none",
                "membership_effect": "none",
                "model": self._model_summary(model),
            }

        scored = []
        for candidate in candidate_set.candidates:
            try:
                snapshot = self.candidate_store.get_snapshot(
                    candidate.candidate_id,
                    candidate.candidate_version,
                )
                if snapshot is None:
                    raise ValueError("candidate_snapshot_missing")
                feedback_snapshot = self._feedback_snapshot(snapshot)
                row = {
                    "feedback_id": "live",
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
                    raise ValueError(reason or "candidate_quality_features_unavailable")
                score = score_model_artifact(model, example.features)
            except (LookupError, ValueError, ShadowArtifactError) as exc:
                logger.warning(
                    "Live recommendation ranking fell back to baseline for candidate %s: %s",
                    candidate.candidate_id,
                    exc,
                )
                return candidate_set, self._fallback_metadata(
                    model,
                    reason=f"scoring_error:{exc}",
                )
            scored.append((candidate, float(score)))

        scored.sort(key=lambda item: (-item[1], item[0].rank, item[0].candidate_id))
        ranked_candidates = tuple(
            RecommendedClassCandidate(
                candidate_id=candidate.candidate_id,
                candidate_version=candidate.candidate_version,
                rank=index,
                anchor_topic=candidate.anchor_topic,
                member_topics=candidate.member_topics,
                discovery_channels=candidate.discovery_channels,
                evidence=candidate.evidence,
            )
            for index, (candidate, _score) in enumerate(scored, 1)
        )
        ranked_set = RecommendedClassCandidateSet(
            candidates=ranked_candidates,
            available_topics=candidate_set.available_topics,
            strategy=candidate_set.strategy,
            strategy_catalog=candidate_set.strategy_catalog,
            evidence_catalog=candidate_set.evidence_catalog,
        )

        live_run_id = str(uuid.uuid4())
        score_by_candidate = {
            candidate.candidate_id: score for candidate, score in scored
        }
        baseline_rank = {
            candidate.candidate_id: candidate.rank for candidate in candidate_set.candidates
        }
        observations = [
            {
                "observation_id": str(uuid.uuid4()),
                "live_run_id": live_run_id,
                "candidate_id": candidate.candidate_id,
                "candidate_version": candidate.candidate_version,
                "strategy_id": candidate_set.strategy.strategy_id,
                "baseline_rank": baseline_rank[candidate.candidate_id],
                "live_rank": candidate.rank,
                "model_id": str(model["model_id"]),
                "candidate_quality_score": score_by_candidate[candidate.candidate_id],
            }
            for candidate in ranked_candidates
        ]
        persistence = self._persist_observations(observations)
        if persistence["status"] != "stored":
            return candidate_set, self._fallback_metadata(
                model,
                reason="live_observation_persistence_failed",
            )

        order_changed = any(
            baseline_rank[candidate.candidate_id] != candidate.rank
            for candidate in ranked_candidates
        )
        return ranked_set, {
            "mode": "live",
            "status": "applied",
            "ranking_effect": "candidate_reorder" if order_changed else "same_order",
            "membership_effect": "none",
            "live_run_id": live_run_id,
            "model": self._model_summary(model),
            "persistence": persistence,
            "candidates": [
                {
                    "candidate_id": candidate.candidate_id,
                    "candidate_version": candidate.candidate_version,
                    "baseline_rank": baseline_rank[candidate.candidate_id],
                    "live_rank": candidate.rank,
                    "candidate_quality_score": score_by_candidate[candidate.candidate_id],
                }
                for candidate in ranked_candidates
            ],
        }

    def _active_model(self) -> dict | None:
        return self.database.fetch_one(
            """
            SELECT m.model_id::text AS model_id, m.objective, m.model_version,
                   m.feature_contract_version, m.artifact
            FROM recommendation_live_deployments d
            JOIN recommendation_model_versions m ON m.model_id = d.model_id
            WHERE d.objective = 'candidate_quality'
              AND m.objective = 'candidate_quality'
              AND m.status = 'OFFLINE_APPROVED'
            """
        )

    @staticmethod
    def _model_summary(model: dict) -> dict:
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
        try:
            with self.database.transaction() as conn:
                for row in rows:
                    conn.execute(
                        """
                        INSERT INTO recommendation_live_observations(
                            observation_id, live_run_id, candidate_id,
                            candidate_version, strategy_id, baseline_rank,
                            live_rank, model_id, candidate_quality_score
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            row["observation_id"],
                            row["live_run_id"],
                            row["candidate_id"],
                            row["candidate_version"],
                            row["strategy_id"],
                            row["baseline_rank"],
                            row["live_rank"],
                            row["model_id"],
                            row["candidate_quality_score"],
                        ),
                    )
        except Exception:
            logger.exception("Failed to persist live recommendation observations")
            return {"status": "error", "count": 0}
        return {"status": "stored", "count": len(rows)}

    @classmethod
    def _fallback_metadata(cls, model: dict, *, reason: str) -> dict:
        return {
            "mode": "live",
            "status": "fallback",
            "reason": reason,
            "ranking_effect": "baseline_fallback",
            "membership_effect": "none",
            "model": cls._model_summary(model),
        }


recommendation_live_ranker = RecommendationLiveRanker()
