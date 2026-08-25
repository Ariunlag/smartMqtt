from fastapi import APIRouter, HTTPException
from models.api_models import TopicListResponse, TopicResponse, TopicSubscribeRequest
from services.topic_manager import DuplicateAliasSubscriptionError, topic_manager

router = APIRouter(tags=["Topics"])


@router.get("/topics", response_model=TopicListResponse)
async def get_topics():
    return TopicListResponse(topics=topic_manager.get_subscribed_topics())


@router.post("/subscribe", response_model=TopicResponse)
async def subscribe_to_topic(req: TopicSubscribeRequest):
    if not req.topic:
        raise HTTPException(status_code=400, detail="Topic required")
    try:
        topic_manager.subscribe(req.topic)
    except DuplicateAliasSubscriptionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return TopicResponse(status="subscribed", topic=req.topic)


@router.post("/unsubscribe", response_model=TopicResponse)
async def unsubscribe_from_topic(req: TopicSubscribeRequest):
    if not req.topic:
        raise HTTPException(status_code=400, detail="Topic required")
    ok = topic_manager.unsubscribe(req.topic)
    if not ok:
        raise HTTPException(status_code=404, detail="Topic not found")
    return TopicResponse(status="unsubscribed", topic=req.topic)
