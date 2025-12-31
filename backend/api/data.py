from fastapi import APIRouter, Query
from typing import List
from models.api_models import TopicListResponse, MeasurementSeriesResponse
from services.query_manager import query_manager

router = APIRouter(tags=["Data"])

# 1. List all measurements
@router.get("/measurements", response_model=TopicListResponse)
async def list_measurements():
    found_measurements = await query_manager.list_measurements()
    return {"topics": found_measurements}

# 2. Get timeseries data (default last 1h)
@router.get("/timeseries", response_model=List[MeasurementSeriesResponse])
async def get_timeseries(
    names: List[str] = Query(..., alias="names[]", description="List of measurement names")
):
    return await query_manager.get_timeseries(names, start="-30d")


# 3. Get last N messages across all topics
@router.get("/messages")
async def get_messages(limit: int = 200):
    rows = await query_manager.get_recent_messages(limit=limit)
    return {"messages": rows}