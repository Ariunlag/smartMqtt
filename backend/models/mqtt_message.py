from pydantic import BaseModel
from datetime import datetime

class MQTTMessage(BaseModel):
    topic: str
    tags: dict
    fields: dict
    timestamp: datetime

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }
