'''
-main FastAPI application.
-Defines the FastAPI app, includes routers
-CORS middleware, and sets up the main entry point.
'''

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from services.service_manager import service_manager

from api import health, socket, topic, duplicates, classes, groups, data

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event():
    await service_manager.startup()

@app.on_event("shutdown")
async def shutdown_event():
    await service_manager.shutdown()

app.include_router(health.router, prefix="/api")
app.include_router(topic.router, prefix="/api")
app.include_router(data.router, prefix="/api")
app.include_router(duplicates.router, prefix="/api")
app.include_router(classes.router, prefix="/api")
app.include_router(groups.router, prefix="/api")
app.include_router(socket.router) 

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000, reload=True)