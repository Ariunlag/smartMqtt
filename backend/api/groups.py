from fastapi import APIRouter, HTTPException
from models.api_models import GroupListResponse
from services.groups_manager import groups_manager

router = APIRouter(tags=["Groups"])


@router.get("/groups", response_model=GroupListResponse)
async def list_groups():
    sets = groups_manager.list_sets()
    return GroupListResponse(sets=sets)


@router.get("/groups/{set_id}/topics")
async def get_group_topics(set_id: str):
    print("[DEBUG] get_group_topics called with set_id:", set_id)
    topics = groups_manager.get_topics_for_set(set_id)
    print("[DEBUG] Requested:", set_id)
    print("[DEBUG] Result:", topics)
    if not topics:
        return {"id": set_id, "topics": []}
    return {"id": set_id, "topics": topics}

