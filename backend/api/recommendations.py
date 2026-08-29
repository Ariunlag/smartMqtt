"""Recommendation APIs.

The legacy Saved-Class recommendation endpoints remain available through
``api/classes.py`` for compatibility, but this router exposes the system-derived
recommended-class workflow used by the dashboard.
"""

import asyncio
import logging
from dataclasses import asdict
from uuid import UUID

from config import config
from fastapi import APIRouter, HTTPException, Request
from models.api_models import RecommendedClassFeedbackRequest
from services.class_recommendation.candidate_feedback import recommended_candidate_store
from services.class_recommendation.discovery import (
    RecommendedClassDiscovery,
    RecommendedClassDiscoveryConfig,
)
from services.class_recommendation.live_ranking import recommendation_live_ranker
from services.class_recommendation.shadow import recommendation_shadow_scorer
from services.class_recommendation.strategies import (
    DEFAULT_STRATEGY_ID,
    TagValueCentroidStrategyConfig,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Class Recommendations"])


class _FilteredRecommendationMetadata:
    """User-facing metadata view that hides configured synthetic topic namespaces."""

    def __init__(self, store, excluded_prefixes: tuple[str, ...]) -> None:
        self.store = store
        self.excluded_prefixes = tuple(excluded_prefixes)

    def all_topic_states(self):
        return [
            row
            for row in self.store.all_topic_states()
            if not self._excluded(str(row["canonical_topic"]))
        ]

    def topic_state(self, topic):
        if self._excluded(str(topic)):
            return None
        return self.store.topic_state(topic)

    def _excluded(self, topic: str) -> bool:
        return any(topic.startswith(prefix) for prefix in self.excluded_prefixes)


@router.get("/topics/{topic:path}/class-recommendations")
async def topic_class_recommendations(topic: str, request: Request):
    """Legacy topic -> Saved Class view kept for API compatibility."""
    result = request.app.state.class_recommendation.recommendations_for_topic(topic)
    return asdict(result)


@router.get("/recommended-classes")
async def recommended_class_candidates(
    request: Request,
    strategy: str = DEFAULT_STRATEGY_ID,
):
    """Return generated candidates with shadow diagnostics and optional live reordering."""
    application = request.app.state.class_recommendation
    metadata_store = _FilteredRecommendationMetadata(
        application.metadata_store,
        config.SYSTEM_RECOMMENDATION_EXCLUDED_TOPIC_PREFIXES,
    )
    discovery = RecommendedClassDiscovery(
        metadata_store=metadata_store,
        pair_store=application.pair_store,
        topic_embedding_store=application.topic_embedding_store,
        identity_store=application.identity_store,
        dupe_store=application.dupe_store,
        config=RecommendedClassDiscoveryConfig(
            min_cluster_size=config.SYSTEM_RECOMMENDATION_MIN_CLUSTER_SIZE,
            min_samples=config.SYSTEM_RECOMMENDATION_MIN_SAMPLES,
            allow_single_cluster=config.SYSTEM_RECOMMENDATION_ALLOW_SINGLE_CLUSTER,
        ),
        centroid_config=TagValueCentroidStrategyConfig(
            threshold=config.SYSTEM_RECOMMENDATION_TAG_VALUE_CENTROID_THRESHOLD,
            min_topic_count=config.SYSTEM_RECOMMENDATION_TAG_VALUE_CENTROID_MIN_TOPICS,
        ),
        strategy_id=strategy,
        candidate_store=recommended_candidate_store,
    )
    try:
        baseline = await asyncio.to_thread(discovery.discover)
    except ValueError as exc:
        if "Unknown recommendation strategy" in str(exc):
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        raise

    try:
        shadow_evaluation = await asyncio.to_thread(
            recommendation_shadow_scorer.evaluate,
            baseline,
        )
    except Exception:  # shadow evaluation must never affect recommendation availability
        logger.exception("Recommendation shadow evaluation failed")
        shadow_evaluation = {
            "mode": "shadow",
            "status": "error",
            "reason": "shadow_evaluation_failed",
            "ranking_effect": "none",
            "baseline_order_preserved": True,
            "models": {},
            "candidates": [],
        }

    try:
        result, live_ranking = await asyncio.to_thread(
            recommendation_live_ranker.apply,
            baseline,
        )
    except Exception:  # live ranking must fail closed to the baseline order
        logger.exception("Recommendation live ranking failed")
        result = baseline
        live_ranking = {
            "mode": "live",
            "status": "fallback",
            "reason": "live_ranking_failed",
            "ranking_effect": "baseline_fallback",
            "membership_effect": "none",
            "model": None,
        }

    payload = asdict(result)
    payload["shadow_evaluation"] = shadow_evaluation
    payload["live_ranking"] = live_ranking
    return payload


@router.post("/recommended-classes/{candidate_id}/feedback")
async def recommended_class_feedback(
    candidate_id: UUID,
    payload: RecommendedClassFeedbackRequest,
):
    """Record an immutable label against an exact persistent candidate version."""
    try:
        return await asyncio.to_thread(
            recommended_candidate_store.record_feedback,
            candidate_id=str(candidate_id),
            candidate_version=payload.candidate_version,
            action_type=payload.action,
            topic=payload.topic,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/class-recommendations/status")
async def class_recommendation_status(request: Request):
    return request.app.state.class_recommendation_processing.status()
