"""Vector-free API models for diagnostic semantic candidate review."""

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
    semantic_class_name: str
    positive_topics: tuple[str, ...]
    removed_topics: tuple[str, ...]
    changed_representations: tuple[str, ...]
    constraints_added: tuple[NegativeMembershipConstraintModel, ...]
    constraints_removed: tuple[NegativeMembershipConstraintModel, ...]
    prototypes: tuple[PrototypeSummaryModel, ...]


class NegativeMembershipConstraintList(BaseModel):
    constraints: tuple[NegativeMembershipConstraintModel, ...]
