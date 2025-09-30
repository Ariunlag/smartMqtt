from fastapi import APIRouter, HTTPException
from models.api_models import ClassListResponse, ClassRecord, CreateClassRequest, UpdateClassRequest
from services.class_manager import class_manager

router = APIRouter(prefix="/classes", tags=["Classes"])


@router.get("/", response_model=ClassListResponse)
async def list_classes():
    return ClassListResponse(classes=class_manager.list_classes())


@router.post("/", response_model=ClassRecord)
async def create_class(req: CreateClassRequest):
    return class_manager.create_class(req.name, req.topics)


@router.put("/{name}", response_model=ClassRecord)
async def update_class(name: str, req: UpdateClassRequest):
    updated = class_manager.update(name, req.topics)
    if not updated:
        raise HTTPException(status_code=404, detail="Class not found")
    return updated


@router.delete("/{name}")
async def delete_class(name: str):
    ok = class_manager.delete(name)
    if not ok:
        raise HTTPException(status_code=404, detail="Class not found")
    return {"status": "deleted", "name": name}
