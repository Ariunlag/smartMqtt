from fastapi import APIRouter
from services.service_manager import service_manager

router = APIRouter(tags=["Health"])

@router.get("/health")
async def health_check():
    statuses = {}
    for service in service_manager.services:
        name = service.__class__.__name__
        if hasattr(service, "check_health"):
            statuses[name] = service.check_health()
        elif hasattr(service, "is_connected"):
            statuses[name] = service.is_connected()
        else:
            statuses[name] = None
    return statuses
