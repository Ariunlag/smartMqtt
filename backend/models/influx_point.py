from pydantic import BaseModel
from typing import Dict, Any
from datetime import datetime

class InfluxPoint(BaseModel):
    measurement: str
    tags: Dict[str, str]
    fields: Dict[str, Any]
    timestamp: datetime
