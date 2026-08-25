"""Immutable domain records for pair-level class recommendation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

PairSource = Literal["tag", "field"]
PairView = Literal["key", "value", "key_value", "schema", "numeric_key"]
PAIR_VIEWS: tuple[PairView, ...] = (
    "key",
    "value",
    "key_value",
    "schema",
    "numeric_key",
)
ALGORITHM_VERSION = "pair-greedy-equal-mean-v1"
REPRESENTATION_CONTRACT_VERSION = "pair-five-view-v1"


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
    is_numeric: bool
    representation_version: int
    texts: tuple[tuple[PairView, str], ...]

    def text_for(self, view: PairView) -> str | None:
        return dict(self.texts).get(view)


@dataclass(frozen=True, slots=True)
class PairEmbeddingRecord:
    representation: PairRepresentation
    vectors: tuple[tuple[PairView, tuple[float, ...]], ...]

    def vector_for(self, view: PairView) -> tuple[float, ...] | None:
        return dict(self.vectors).get(view)


@dataclass(frozen=True, slots=True)
class ClassPairPrototype:
    class_id: str
    class_name: str
    identity: PairIdentity
    centroids: tuple[tuple[PairView, tuple[float, ...]], ...]
    member_count: int
    prototype_version: int

    @property
    def prototype_id(self) -> str:
        return f"{self.class_id}:{self.identity.value}"

    def centroid_for(self, view: PairView) -> tuple[float, ...] | None:
        return dict(self.centroids).get(view)


@dataclass(frozen=True, slots=True)
class ClassProfile:
    class_id: str
    class_name: str
    profile_version: int
    pair_prototypes: tuple[ClassPairPrototype, ...]
    stream_context_centroid: tuple[float, ...] | None


@dataclass(frozen=True, slots=True)
class PairViewScores:
    key: float
    value: float
    key_value: float
    schema: float
    numeric_key: float | None

    def valid(self) -> tuple[tuple[PairView, float], ...]:
        rows: list[tuple[PairView, float]] = [
            ("key", self.key),
            ("value", self.value),
            ("key_value", self.key_value),
            ("schema", self.schema),
        ]
        if self.numeric_key is not None:
            rows.append(("numeric_key", self.numeric_key))
        return tuple(rows)


@dataclass(frozen=True, slots=True)
class MatchedPairEvidence:
    candidate: PairIdentity
    prototype: PairIdentity
    prototype_id: str
    scores: PairViewScores
    compatibility_score: float


@dataclass(frozen=True, slots=True)
class Coverage:
    candidate_pair_count: int
    class_prototype_count: int
    matched_pair_count: int
    candidate_coverage: float
    prototype_coverage: float


@dataclass(frozen=True, slots=True)
class ChannelScores:
    key: float | None
    value: float | None
    key_value: float | None
    schema: float | None
    numeric_key: float | None
    stream_context: float | None

    def valid(self) -> tuple[tuple[str, float], ...]:
        return tuple(
            (name, value)
            for name, value in (
                ("key", self.key),
                ("value", self.value),
                ("key_value", self.key_value),
                ("schema", self.schema),
                ("numeric_key", self.numeric_key),
                ("stream_context", self.stream_context),
            )
            if value is not None
        )


@dataclass(frozen=True, slots=True)
class ClassRecommendation:
    recommendation_id: str
    canonical_topic: str
    original_topic: str
    class_id: str
    class_name: str
    rank: int
    overall_score: float
    channel_scores: ChannelScores
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
