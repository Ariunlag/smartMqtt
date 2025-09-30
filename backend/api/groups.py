from fastapi import APIRouter, HTTPException
from models.api_models import GroupListResponse
from services.groups_manager import groups_manager

router = APIRouter(tags=["Groups"])


@router.get("/groups", response_model=GroupListResponse)
async def list_groups():
    sets = groups_manager.list_sets()
    return GroupListResponse(sets=sets)


@router.get("/{set_id}/topics")
async def get_group_topics(set_id: str):
    """Return all topics belonging to the given group (set_id)."""
    topics = groups_manager.get_topics_for_set(set_id)
    if topics is None:
        raise HTTPException(status_code=404, detail=f"Group {set_id} not found")
    return {"set_id": set_id, "topics": topics}