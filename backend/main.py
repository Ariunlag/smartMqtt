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
from services.class_recommendation.processing import RecommendationObservationFanout
from services.service_manager import service_manager

ClassRecommendationApplicationFactory = Callable[[], ClassRecommendationApplication]


def _build_default_class_recommendation_application() -> ClassRecommendationApplication:
    """Build the production recommender lazily during application startup."""
    from services.embedding_manager import embedding_manager

    application = build_class_recommendation_application(
        model=embedding_manager.model,
        stream_context_refresher=embedding_manager.embed_flattened_topic,
        processing_capacity=config.CLASS_RECOMMENDATION_QUEUE_MAXSIZE,
    )
    from services.class_recommendation.adaptive import AdaptiveRecommendations
    from services.class_recommendation.adaptive_discovery import DiscoveryConfig
    from services.class_recommendation.adaptive_series import (
        InfluxSeriesSource,
        SeriesConfig,
        SeriesShapeProvider,
    )
    from services.influx.client import influx_client

    series = None if config.ADAPTIVE_SERIES_MODE == "off" else SeriesShapeProvider(
        SeriesConfig(
            step_seconds=config.ADAPTIVE_SERIES_STEP,
            bins=config.ADAPTIVE_SERIES_BINS,
            min_points=config.ADAPTIVE_SERIES_MIN_POINTS,
        ),
        active=config.ADAPTIVE_SERIES_MODE == "active",
    )

    application.adaptive = AdaptiveRecommendations(
        embedding_manager.model,
        application.identity_store,
        environment_id=config.RECOMMENDATION_ENVIRONMENT,
        model_id=config.EMBEDDING_MODEL,
        threshold=config.ADAPTIVE_SIMILARITY_THRESHOLD,
        interval=config.ADAPTIVE_LEARNING_INTERVAL,
        min_labels=config.ADAPTIVE_MIN_LABELS,
        excluded_prefixes=config.SYSTEM_RECOMMENDATION_EXCLUDED_TOPIC_PREFIXES,
        discovery_config=DiscoveryConfig(
            exact_limit=config.ADAPTIVE_EXACT_LIMIT,
            neighbors=config.ADAPTIVE_NEIGHBORS,
        ),
        series_provider=series,
        series_source=(
            InfluxSeriesSource(influx_client, config.INFLUX_BUCKET) if series else None
        ),
    )
    # Production evidence remains the original independent pair/stream contract:
    # key, value, key_value, schema, and stream_context. The adaptive subsystem is
    # retained as a best-effort secondary observer for experimentation/editing, but it
    # cannot replace or block the stable recommendation materialization path.
    application.processing_service.application = RecommendationObservationFanout(
        application,
        application.adaptive,
    )
    return application


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
        allow_origins=list(config.CORS_ALLOWED_ORIGINS),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(health.router, prefix="/api")
    application.include_router(topic.router, prefix="/api")
    application.include_router(data.router, prefix="/api")
    application.include_router(duplicates.router, prefix="/api")
    application.include_router(classes.router, prefix="/api")
    application.include_router(recommendations.router, prefix="/api")
    application.include_router(socket.router)
    return application


app = create_app()

if __name__ == "__main__":
    import uvicorn

    host = os.getenv("BACKEND_HOST", "0.0.0.0")
    port = int(os.getenv("BACKEND_PORT", "8000"))
    uvicorn.run(app, host=host, port=port, reload=False)
