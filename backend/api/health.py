from fastapi import APIRouter, Response
from services.service_manager import service_manager

router = APIRouter(tags=["Health"])


@router.get("/health/live")
async def liveness():
    """Liveness: the process is up. Never depends on external dependencies."""
    return {"status": "alive"}


@router.get("/health/ready")
async def readiness(response: Response):
    """Readiness: all required dependencies are healthy (bounded checks)."""
    snapshot = await service_manager.check_all()
    ready = service_manager.is_ready(snapshot)
    if not ready:
        response.status_code = 503
    return {
        "status": "ready" if ready else "not_ready",
        "dependencies": snapshot,
    }


@router.get("/health/details")
async def health_details():
    """Full per-dependency status with check latency. Always 200."""
    snapshot = await service_manager.check_all()
    return {
        "status": "ready" if service_manager.is_ready(snapshot) else "not_ready",
        "dependencies": snapshot,
    }


@router.get("/health")
async def health_check():
    """Backward-compatible endpoint (class-name -> healthy bool).

    Retained temporarily for the existing frontend bootstrap.
    """
    snapshot = await service_manager.check_all()
    return {name: info["healthy"] for name, info in snapshot.items()}
