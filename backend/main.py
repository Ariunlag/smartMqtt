'''
-main FastAPI application.
-Defines the FastAPI app, includes routers
-CORS middleware, and sets up the main entry point.
'''

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from services.service_manager import service_manager

from api import health, socket, topic, duplicates, classes, groups, data


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup is non-blocking: the app comes up (liveness) even if a dependency
    # is temporarily down; the dependency monitor recovers it in the background.
    await service_manager.startup()
    try:
        yield
    finally:
        await service_manager.shutdown()


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api")
app.include_router(topic.router, prefix="/api")
app.include_router(data.router, prefix="/api")
app.include_router(duplicates.router, prefix="/api")
app.include_router(classes.router, prefix="/api")
app.include_router(groups.router, prefix="/api")
app.include_router(socket.router) 

if __name__ == "__main__":
    import uvicorn
    host = os.getenv("BACKEND_HOST", "0.0.0.0")
    port = int(os.getenv("BACKEND_PORT", "8000"))
    uvicorn.run(app, host=host, port=port, reload=False)