from fastapi import APIRouter, HTTPException
from models.api_models import DupeListResponse, DupeRecord, ConfirmDupeRequest, DupeAction
from services.dupe_manager import dupe_manager

router = APIRouter(tags=["Duplicates"])

@router.get("/duplicates", response_model=DupeListResponse)
async def list_pending_dupes():
    return DupeListResponse(duplicates=dupe_manager.list_pending())

@router.post("/duplicate-confirm", response_model=DupeRecord)
async def confirm_dupe(req: ConfirmDupeRequest):
    topic_a, topic_b = req.topics

    if req.action == DupeAction.UNSUBSCRIBE:
        try:
            rec = dupe_manager.confirm_duplicate(topic_a, topic_b, req.target)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    elif req.action == DupeAction.KEEP_BOTH:
        rec = dupe_manager.keep_both(topic_a, topic_b)
    else:
        raise HTTPException(status_code=400, detail="Invalid action")

    if not rec:
        raise HTTPException(status_code=404, detail="Duplicate pair not found")

    return rec
