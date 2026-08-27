"""Immutable domain records for pair-level class recommendation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .evidence import EVIDENCE_CATALOG, PAIR_EVIDENCE_IDS, EvidenceId

PairSource = Literal["tag", "field"]
PairView = EvidenceId
PAIR_VIEWS: tuple[EvidenceId, ...] = PAIR_EVIDENCE_IDS
ALGORITHM_VERSION = "pair-greedy-evidence-registry-v2"
REPRESENTATION_CONTRACT_VERSION = "pair-evidence-registry-v2"


@dataclass(frozen=True, slots=True, order=True)
class PairIdentity:
    source: PairSource
    normalized_key: str
    datatype: str

    @property
    def value(self) -> str:
        return f"{self.source}:{self.normalized_key}:{self.datatype}"


@dataclass(frozen=True, slots=True)
class PairRepresentation:
    canonical_topic: str
    original_topic: str
    identity: PairIdentity
    raw_key: str
    raw_value: object
    normalized_key: str
    normalized_value: str
    datatype: str
    representation_version: int
    texts: tuple[tuple[EvidenceId, str], ...]

    def text_for(self, evidence_id: EvidenceId) -> str | None:
        return dict(self.texts).get(evidence_id)


@dataclass(frozen=True, slots=True)
class PairEmbeddingRecord:
    representation: PairRepresentation
    vectors: tuple[tuple[EvidenceId, tuple[float, ...]], ...]

    def vector_for(self, evidence_id: EvidenceId) -> tuple[float, ...] | None:
        return dict(self.vectors).get(evidence_id)


@dataclass(frozen=True, slots=True)
class ClassPairPrototype:
    class_id: str
    class_name: str
    identity: PairIdentity
    centroids: tuple[tuple[EvidenceId, tuple[float, ...]], ...]
    member_count: int
    prototype_version: int

    @property
    def prototype_id(self) -> str:
        return f"{self.class_id}:{self.identity.value}"

    def centroid_for(self, evidence_id: EvidenceId) -> tuple[float, ...] | None:
        return dict(self.centroids).get(evidence_id)


@dataclass(frozen=True, slots=True)
class ClassProfile:
    class_id: str
    class_name: str
    profile_version: int
    pair_prototypes: tuple[ClassPairPrototype, ...]
    stream_context_centroid: tuple[float, ...] | None


@dataclass(frozen=True, slots=True)
class EvidenceScore:
    evidence_id: EvidenceId
    score: float


@dataclass(frozen=True, slots=True)
class EvidenceScores:
    """Ordered evidence scores whose shape is defined by the evidence registry."""

    items: tuple[EvidenceScore, ...]

    @classmethod
    def from_values(cls, values: dict[EvidenceId, float | None]) -> "EvidenceScores":
        known = {definition.evidence_id for definition in EVIDENCE_CATALOG}
        unknown = set(values) - known
        if unknown:
            raise ValueError(
                "Unknown recommendation evidence ids: " + ", ".join(sorted(unknown))
            )
        return cls(
            tuple(
                EvidenceScore(definition.evidence_id, float(values[definition.evidence_id]))
                for definition in EVIDENCE_CATALOG
                if values.get(definition.evidence_id) is not None
            )
        )

    def get(self, evidence_id: EvidenceId) -> float | None:
        return next(
            (item.score for item in self.items if item.evidence_id == evidence_id),
            None,
        )

    def valid(self) -> tuple[tuple[EvidenceId, float], ...]:
        return tuple((item.evidence_id, item.score) for item in self.items)


# Transitional aliases keep legacy imports working while the underlying structure is
# registry-driven rather than one dataclass field per evidence channel.
PairViewScores = EvidenceScores
ChannelScores = EvidenceScores


@dataclass(frozen=True, slots=True)
class MatchedPairEvidence:
    candidate: PairIdentity
    prototype: PairIdentity
    prototype_id: str
    scores: EvidenceScores
    compatibility_score: float


@dataclass(frozen=True, slots=True)
class Coverage:
    candidate_pair_count: int
    class_prototype_count: int
    matched_pair_count: int
    candidate_coverage: float
    prototype_coverage: float


@dataclass(frozen=True, slots=True)
class ClassRecommendation:
    recommendation_id: str
    canonical_topic: str
    original_topic: str
    class_id: str
    class_name: str
    rank: int
    overall_score: float
    channel_scores: EvidenceScores
    valid_channels: tuple[str, ...]
    coverage: Coverage
    matched_pairs: tuple[MatchedPairEvidence, ...]
    unmatched_candidate_pairs: tuple[PairIdentity, ...]
    unmatched_prototypes: tuple[PairIdentity, ...]
    class_profile_version: int
    topic_representation_version: int
    duplicate_pending: bool
    algorithm_version: str = ALGORITHM_VERSION


@dataclass(frozen=True, slots=True)
class TopicRecommendations:
    canonical_topic: str
    original_topic: str
    topic_representation_version: int
    recommendations: tuple[ClassRecommendation, ...]
