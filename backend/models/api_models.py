from datetime import datetime
from enum import Enum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, field_validator, model_validator

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
# Classes (user-owned Saved Classes)
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
# System Recommended Class feedback
# ---------------------------


RecommendedClassFeedbackAction = Literal[
    "KEEP_TOPIC",
    "REMOVE_TOPIC",
    "ACCEPT_CANDIDATE",
    "DISMISS_CANDIDATE",
]


class RecommendedClassFeedbackRequest(BaseModel):
    action: RecommendedClassFeedbackAction
    candidate_version: int
    topic: str | None = None
    shadow_run_id: UUID | None = None
    live_run_id: UUID | None = None

    @model_validator(mode="after")
    def validate_action_scope(self):
        topic_actions = {"KEEP_TOPIC", "REMOVE_TOPIC"}
        if self.candidate_version < 1:
            raise ValueError("candidate_version must be at least 1")
        if self.action in topic_actions and not self.topic:
            raise ValueError(f"{self.action} requires a topic")
        if self.action not in topic_actions and self.topic is not None:
            raise ValueError(f"{self.action} does not accept a topic")
        return self
