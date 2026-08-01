"""Vector-free API models for diagnostic semantic candidate review."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class CandidateIdentityModel(BaseModel):
    representation_name: str
    member_topics: tuple[str, ...]


class PendingSemanticCandidateModel(CandidateIdentityModel):
    candidate_index: int | None = None


class SemanticReviewState(BaseModel):
    candidates: tuple[PendingSemanticCandidateModel, ...]
    available_unknown_topics: tuple[str, ...]


class SemanticMembershipReviewRequest(BaseModel):
    identity: CandidateIdentityModel
    class_id: str
    semantic_class_name: str
    kept_topics: tuple[str, ...]
    removed_topics: tuple[str, ...]
    added_topics: tuple[str, ...]


class NegativeMembershipConstraintModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    topic: str
    semantic_class_name: str


class PrototypeSummaryModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    representation_name: str
    member_topics: tuple[str, ...]
    member_count: int


class SemanticReviewResult(BaseModel):
    class_id: str
    semantic_class_name: str
    registry_updated: bool
    positive_topics: tuple[str, ...]
    removed_topics: tuple[str, ...]
    changed_representations: tuple[str, ...]
    constraints_added: tuple[NegativeMembershipConstraintModel, ...]
    constraints_removed: tuple[NegativeMembershipConstraintModel, ...]
    prototypes: tuple[PrototypeSummaryModel, ...]


class NegativeMembershipConstraintList(BaseModel):
    constraints: tuple[NegativeMembershipConstraintModel, ...]


class SemanticClassDefinitionModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    class_id: str
    semantic_class_name: str


class SemanticClassList(BaseModel):
    classes: tuple[SemanticClassDefinitionModel, ...]


class SemanticProcessingStatusModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    running: bool
    enabled: bool
    queue_size: int
    queue_capacity: int
    submitted_count: int
    processed_count: int
    failed_count: int
    dropped_count: int
    last_processed_topic: str | None
    last_error_topic: str | None
    last_error_message: str | None


class SemanticDiscoveryStatusModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    running: bool
    enabled: bool
    request_pending: bool
    pool_version: int
    last_processed_version: int | None
    run_count: int
    published_count: int
    failed_count: int
    stale_discard_count: int
    candidate_count: int
    noise_topic_count: int
    last_error_message: str | None


class SemanticPersistenceStatusModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    enabled: bool
    running: bool
    restored: bool
    degraded: bool
    schema_version: int
    current_generation: int
    persisted_generation: int | None
    save_pending: bool
    save_count: int
    restore_count: int
    failed_save_count: int
    failed_restore_count: int
    last_saved_at: datetime | None
    last_restored_at: datetime | None
    last_error_message: str | None
    compatibility_error: str | None
