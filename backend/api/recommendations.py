"""Recommendation APIs.

The legacy Saved-Class recommendation endpoints remain available through
``api/classes.py`` for compatibility, but this router exposes the system-derived
recommended-class workflow used by the dashboard.
"""

import asyncio
from dataclasses import asdict

from config import config
from fastapi import APIRouter, HTTPException, Request
from models.api_models import RecommendedClassFeedbackRequest
from services.class_recommendation.candidate_feedback import recommended_candidate_store
from services.class_recommendation.discovery import (
    RecommendedClassDiscovery,
    RecommendedClassDiscoveryConfig,
)
from services.class_recommendation.strategies import (
    DEFAULT_STRATEGY_ID,
    TagValueCentroidStrategyConfig,
)

router = APIRouter(tags=["Class Recommendations"])


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
    """Return system candidates generated from the selected strategy."""
    application = request.app.state.class_recommendation
    discovery = RecommendedClassDiscovery(
        metadata_store=application.metadata_store,
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
        result = await asyncio.to_thread(discovery.discover)
    except ValueError as exc:
        if "Unknown recommendation strategy" in str(exc):
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        raise
    return asdict(result)


@router.post("/recommended-classes/{candidate_id}/feedback")
async def recommended_class_feedback(
    candidate_id: str,
    payload: RecommendedClassFeedbackRequest,
):
    """Record an immutable label against an exact persistent candidate version."""
    try:
        return await asyncio.to_thread(
            recommended_candidate_store.record_feedback,
            candidate_id=candidate_id,
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
