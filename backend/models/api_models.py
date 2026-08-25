from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, field_validator

# ---------------------------
# Topics
# ---------------------------


class TopicListResponse(BaseModel):
    topics: list[str]


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
    value: float  # single numeric field for UI plotting


class MeasurementSeriesResponse(BaseModel):
    measurement: str
    points: list[MeasurementPoint]


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
    topics: list[str]
    score: float
    status: DupeStatus


class DupeListResponse(BaseModel):
    duplicates: list[DupeRecord]


class ConfirmDupeRequest(BaseModel):
    topics: list[str]
    action: DupeAction
    target: str | None = None

    @field_validator("topics")
    def must_have_two(cls, v):
        if len(v) != 2:
            raise ValueError("Exactly 2 topics required")
        return v


# ---------------------------
# Classes (user groups)
# ---------------------------


class ClassRecord(BaseModel):
    class_id: str
    name: str
    topics: list[str]
    profile_version: int


class ClassListResponse(BaseModel):
    classes: list[ClassRecord]


class CreateClassRequest(BaseModel):
    name: str
    topics: list[str]


class UpdateClassRequest(BaseModel):
    topics: list[str]


class ClassRecommendationActionRequest(BaseModel):
    action: Literal[
        "RECOMMENDATION_ACCEPT",
        "RECOMMENDATION_REJECT",
        "RECOMMENDATION_DISMISS",
        "MANUAL_ADD",
        "MANUAL_REMOVE",
    ]
    topic: str
    topic_representation_version: int | None = None
    class_profile_version: int | None = None
    recommendation_id: str | None = None


# ---------------------------
# Groups (tag-based)
# ---------------------------


class TagSetRecord(BaseModel):
    id: str
    tags: list[str]


class GroupListResponse(BaseModel):
    sets: list[TagSetRecord]


class GroupTopicResponse(BaseModel):
    id: str
    topics: list[str]
