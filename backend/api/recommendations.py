"""Recommendation APIs.

The legacy Saved-Class recommendation endpoints remain available through
``api/classes.py`` for compatibility, but this router exposes the system-derived
recommended-class candidate workflow used by the dashboard.
"""

import asyncio
from dataclasses import asdict

from config import config
from fastapi import APIRouter, Request
from services.class_recommendation.discovery import (
    RecommendedClassDiscovery,
    RecommendedClassDiscoveryConfig,
)

router = APIRouter(tags=["Class Recommendations"])


@router.get("/topics/{topic:path}/class-recommendations")
async def topic_class_recommendations(topic: str, request: Request):
    """Legacy topic -> Saved Class view kept for API compatibility."""
    result = request.app.state.class_recommendation.recommendations_for_topic(topic)
    return asdict(result)


@router.get("/recommended-classes")
async def recommended_class_candidates(request: Request):
    """Return system-derived candidate classes without exposing Saved Classes."""
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
    )
    result = await asyncio.to_thread(discovery.discover)
    return asdict(result)


@router.get("/class-recommendations/status")
async def class_recommendation_status(request: Request):
    return request.app.state.class_recommendation_processing.status()
