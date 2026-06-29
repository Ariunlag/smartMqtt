from fastapi import APIRouter, HTTPException
from models.api_models import ClassListResponse, ClassRecord, CreateClassRequest, UpdateClassRequest
from services.class_manager import class_manager

router = APIRouter(prefix="/classes", tags=["Classes"])


@router.get("/", response_model=ClassListResponse)
async def list_classes():
    return ClassListResponse(classes=class_manager.list_classes())


@router.post("/", response_model=ClassRecord)
async def create_class(req: CreateClassRequest):
    try:
        return class_manager.create_class(req.name, req.topics)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.put("/{name}", response_model=ClassRecord)
async def update_class(name: str, req: UpdateClassRequest):
    updated = class_manager.update_class(name, req.topics)
    if not updated:
        raise HTTPException(status_code=404, detail="Class not found")
    return updated


@router.delete("/{name}")
async def delete_class(name: str):
    try:
        class_manager.delete_class(name)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "deleted", "name": name}
