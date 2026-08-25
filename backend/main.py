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
    recommendations,
    socket,
    topic,
)
from config import config
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from services.class_recommendation import (
    ClassRecommendationApplication,
    build_class_recommendation_application,
)
from services.service_manager import service_manager

ClassRecommendationApplicationFactory = Callable[[], ClassRecommendationApplication]


def _build_default_class_recommendation_application() -> ClassRecommendationApplication:
    """Build the production recommender lazily during application startup."""
    from services.embedding_manager import embedding_manager

    return build_class_recommendation_application(
        model=embedding_manager.model,
        stream_context_refresher=embedding_manager.embed_flattened_topic,
        processing_capacity=config.CLASS_RECOMMENDATION_QUEUE_MAXSIZE,
    )


def create_app(
    *,
    class_recommendation_application: ClassRecommendationApplication | None = None,
    class_recommendation_application_factory: (
        ClassRecommendationApplicationFactory | None
    ) = None,
    manage_services: bool = True,
) -> FastAPI:
    """Create one FastAPI app with one class recommendation composition root."""
    if (
        class_recommendation_application is not None
        and class_recommendation_application_factory is not None
    ):
        raise ValueError(
            "Provide class_recommendation_application or its factory, not both"
        )
    factory = (
        class_recommendation_application_factory
        or _build_default_class_recommendation_application
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if getattr(app.state, "class_recommendation", None) is None:
            app.state.class_recommendation = factory()
            app.state.class_recommendation_processing = (
                app.state.class_recommendation.processing_service
            )
        if manage_services:
            # Startup is non-blocking for external dependencies; the monitor
            # recovers unavailable services in the background.
            await service_manager.startup(app.state.class_recommendation)
        try:
            yield
        finally:
            if manage_services:
                await service_manager.shutdown()

    application = FastAPI(lifespan=lifespan)
    if class_recommendation_application is not None:
        application.state.class_recommendation = class_recommendation_application
        application.state.class_recommendation_processing = (
            class_recommendation_application.processing_service
        )
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
    application.include_router(recommendations.router, prefix="/api")
    application.include_router(socket.router)
    return application


app = create_app()

if __name__ == "__main__":
    import uvicorn

    host = os.getenv("BACKEND_HOST", "0.0.0.0")
    port = int(os.getenv("BACKEND_PORT", "8000"))
    uvicorn.run(app, host=host, port=port, reload=False)
