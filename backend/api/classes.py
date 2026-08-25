from fastapi import APIRouter, HTTPException, Request
from models.api_models import (
    ClassListResponse,
    ClassRecommendationActionRequest,
    ClassRecord,
    CreateClassRequest,
    UpdateClassRequest,
)
from services.class_recommendation.application import StaleRecommendationError

router = APIRouter(prefix="/classes", tags=["Classes"])


@router.get("/", response_model=ClassListResponse)
async def list_classes(request: Request):
    return ClassListResponse(
        classes=request.app.state.class_recommendation.class_manager.list_classes()
    )


@router.post("/", response_model=ClassRecord)
async def create_class(req: CreateClassRequest, request: Request):
    try:
        application = request.app.state.class_recommendation
        return application.create_class(req.name, req.topics)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.put("/{name}", response_model=ClassRecord)
async def update_class(name: str, req: UpdateClassRequest, request: Request):
    application = request.app.state.class_recommendation
    updated = application.update_class(name, req.topics)
    if not updated:
        raise HTTPException(status_code=404, detail="Class not found")
    return updated


@router.delete("/{name}")
async def delete_class(name: str, request: Request):
    application = request.app.state.class_recommendation
    try:
        application.delete_class(name)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "deleted", "name": name}


@router.get("/{name}/recommendations")
async def class_recommendations(name: str, request: Request):
    try:
        rows = request.app.state.class_recommendation.recommendations_for_class(name)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"class_name": name, "recommendations": rows}


@router.post("/{name}/recommendation-actions")
async def apply_recommendation_action(
    name: str, payload: ClassRecommendationActionRequest, request: Request
):
    try:
        return request.app.state.class_recommendation.apply_action(
            action=payload.action,
            class_name=name,
            topic=payload.topic,
            topic_version=payload.topic_representation_version,
            class_profile_version=payload.class_profile_version,
            recommendation_id=payload.recommendation_id,
        )
    except StaleRecommendationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
