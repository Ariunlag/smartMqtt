"""Topic-oriented views over the single class recommendation engine."""

from dataclasses import asdict

from fastapi import APIRouter, Request

router = APIRouter(tags=["Class Recommendations"])


@router.get("/topics/{topic:path}/class-recommendations")
async def topic_class_recommendations(topic: str, request: Request):
    result = request.app.state.class_recommendation.recommendations_for_topic(topic)
    return asdict(result)


@router.get("/class-recommendations/status")
async def class_recommendation_status(request: Request):
    return request.app.state.class_recommendation_processing.status()
