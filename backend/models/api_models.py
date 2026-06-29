from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
from enum import Enum
from pydantic import field_validator



# ---------------------------
# Topics
# ---------------------------

class TopicListResponse(BaseModel):
    topics: List[str]


class TopicSubscribeRequest(BaseModel):
    topic: str


class TopicResponse(BaseModel):
    status: str
    topic: str


# ---------------------------
# Measurements (time-series)
# ---------------------------

class MeasurementPoint(BaseModel):
    timestamp: datetime
    value: float   # single numeric field for UI plotting


class MeasurementSeriesResponse(BaseModel):
    measurement: str
    points: List[MeasurementPoint]


# ---------------------------
# Duplicate Detection
# ---------------------------

class DupeStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED_DUPLICATE = "CONFIRMED_DUPLICATE"
    NOT_DUPLICATE = "NOT_DUPLICATE"

class DupeAction(str, Enum):
    KEEP_BOTH = "KEEP_BOTH"
    UNSUBSCRIBE = "UNSUBSCRIBE"


class DupeRecord(BaseModel):
    topics: List[str]
    score: float
    status: DupeStatus

class DupeListResponse(BaseModel):
    duplicates: List[DupeRecord]

class ConfirmDupeRequest(BaseModel):
    topics: List[str]
    action: DupeAction
    target: Optional[str] = None

    @field_validator("topics")
    def must_have_two(cls, v):
        if len(v) != 2:
            raise ValueError("Exactly 2 topics required")
        return v


# ---------------------------
# Classes (user groups)
# ---------------------------

class ClassRecord(BaseModel):
    name: str
    topics: List[str]


class ClassListResponse(BaseModel):
    classes: List[ClassRecord]


class CreateClassRequest(BaseModel):
    name: str
    topics: List[str]


class UpdateClassRequest(BaseModel):
    topics: List[str]


# ---------------------------
# Groups (tag-based)
# ---------------------------

class TagSetRecord(BaseModel):
    id: str
    tags: List[str]

class GroupListResponse(BaseModel):
    sets: List[TagSetRecord]


class GroupTopicResponse(BaseModel):
    id: str
    topics: List[str]
