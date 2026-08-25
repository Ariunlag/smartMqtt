from fastapi import APIRouter, HTTPException, Request
from models.api_models import (
    ConfirmDupeRequest,
    DupeAction,
    DupeListResponse,
    DupeRecord,
)
from services.dupe_manager import dupe_manager
from services.duplicate.canonicalization_service import (
    DuplicateCanonicalizationConflict,
)

router = APIRouter(tags=["Duplicates"])


@router.get("/duplicates", response_model=DupeListResponse)
async def list_pending_dupes():
    return DupeListResponse(duplicates=dupe_manager.list_pending())


@router.post("/duplicate-confirm", response_model=DupeRecord)
async def confirm_dupe(req: ConfirmDupeRequest, request: Request):
    topic_a, topic_b = req.topics

    if req.action == DupeAction.UNSUBSCRIBE:
        try:
            rec = dupe_manager.confirm_duplicate(
                topic_a,
                topic_b,
                req.target,
                request.app.state.class_recommendation,
            )
        except DuplicateCanonicalizationConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    elif req.action == DupeAction.KEEP_BOTH:
        previous = dupe_manager.find_pair(topic_a, topic_b)
        rec = dupe_manager.keep_both(topic_a, topic_b)
        if rec is not None and previous is not None and previous["status"] == "PENDING":
            request.app.state.class_recommendation.metadata_store.audit(
                action_type="DUPLICATE_KEEP_BOTH",
                details={
                    "canonical_topic": topic_a,
                    "original_topic": topic_b,
                    "duplicate_state": "NOT_DUPLICATE",
                },
            )
    else:
        raise HTTPException(status_code=400, detail="Invalid action")

    if not rec:
        raise HTTPException(status_code=404, detail="Duplicate pair not found")

    return rec


@router.get("/duplicate-identity/{topic:path}")
async def duplicate_identity(topic: str, request: Request):
    identity = request.app.state.class_recommendation.identity_store.get(topic)
    return {
        "topic": identity.topic,
        "canonical_topic": identity.canonical_topic,
        "state": "DUPLICATE_ALIAS" if identity.is_alias else "ACTIVE_CANONICAL",
    }


@router.get("/duplicate-identity-diagnostics")
async def duplicate_identity_diagnostics(request: Request):
    return {
        "legacy_unresolved_confirmations": (
            request.app.state.class_recommendation.identity_store.legacy_unresolved_confirmations()
        )
    }
