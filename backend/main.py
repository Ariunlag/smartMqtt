"""
-main FastAPI application.
-Defines the FastAPI app, includes routers
-CORS middleware, and sets up the main entry point.
"""

import os
from collections.abc import Callable
from contextlib import asynccontextmanager

from api import (
    classes,
    data,
    duplicates,
    groups,
    health,
    semantic_review,
    socket,
    topic,
)
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from services.semantic import (
    SemanticApplication,
    SemanticClassDecisionConfig,
    SemanticClassDecisionPolicy,
    build_semantic_application,
)
from services.service_manager import service_manager

SemanticApplicationFactory = Callable[[], SemanticApplication]


def _build_default_semantic_application() -> SemanticApplication:
    """Build configured semantic state lazily during application startup."""
    from services.embedding_manager import embedding_manager

    # The registry is intentionally empty until reviewed prototypes receive
    # explicit class IDs in the next integration step. These thresholds are
    # therefore not exercised by the default composition.
    decision_policy = SemanticClassDecisionPolicy(
        SemanticClassDecisionConfig(
            known_min_top1_votes=6,
            known_min_mean_similarity=1.0,
            known_min_similarity_margin=2.0,
            unknown_max_mean_similarity=-1.0,
        )
    )
    return build_semantic_application(
        embedding_model=embedding_manager.model,
        known_classes=(),
        decision_policy=decision_policy,
    )


def create_app(
    *,
    semantic_application: SemanticApplication | None = None,
    semantic_application_factory: SemanticApplicationFactory | None = None,
    manage_services: bool = True,
) -> FastAPI:
    """Create one FastAPI app with one isolated semantic composition root."""
    if semantic_application is not None and semantic_application_factory is not None:
        raise ValueError(
            "Provide semantic_application or semantic_application_factory, not both"
        )
    factory = semantic_application_factory or _build_default_semantic_application

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if getattr(app.state, "semantic_application", None) is None:
            app.state.semantic_application = factory()
        if manage_services:
            # Startup is non-blocking for external dependencies; the monitor
            # recovers unavailable services in the background.
            await service_manager.startup()
        try:
            yield
        finally:
            if manage_services:
                await service_manager.shutdown()

    application = FastAPI(lifespan=lifespan)
    if semantic_application is not None:
        application.state.semantic_application = semantic_application
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(health.router, prefix="/api")
    application.include_router(topic.router, prefix="/api")
    application.include_router(data.router, prefix="/api")
    application.include_router(duplicates.router, prefix="/api")
    application.include_router(classes.router, prefix="/api")
    application.include_router(groups.router, prefix="/api")
    application.include_router(semantic_review.router, prefix="/api")
    application.include_router(socket.router)
    return application


app = create_app()

if __name__ == "__main__":
    import uvicorn

    host = os.getenv("BACKEND_HOST", "0.0.0.0")
    port = int(os.getenv("BACKEND_PORT", "8000"))
    uvicorn.run(app, host=host, port=port, reload=False)
