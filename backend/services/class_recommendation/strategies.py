"""Pluggable recommendation strategies over independently stored evidence.

The representation layer never fuses evidence. Strategies consume the same raw pair
records, stream vectors, and per-evidence similarities so experiments can change how
recommendations are formed without rematerializing embeddings.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol, Sequence

from sklearn.cluster import HDBSCAN

from .domain import PairEmbeddingRecord
from .evidence import DISCOVERY_EVIDENCE_IDS

DistanceMatrix = tuple[tuple[float, ...], ...]
ClusterLabels = Callable[[str, DistanceMatrix], Sequence[int]]
DEFAULT_STRATEGY_ID = "independent_hdbscan"


@dataclass(frozen=True, slots=True)
class RecommendationStrategyDefinition:
    strategy_id: str
    label: str
    description: str


@dataclass(frozen=True, slots=True)
class RecommendationStrategyInput:
    """One immutable evidence snapshot shared by every recommendation strategy."""

    topics: tuple[str, ...]
    versions: dict[str, int]
    pairs_by_topic: dict[str, tuple[PairEmbeddingRecord, ...]]
    stream_vectors: dict[str, tuple[float, ...] | None]
    symmetric_scores: dict[tuple[str, str], dict[str, float | None]]


@dataclass(frozen=True, slots=True)
class StrategyCandidateGroup:
    members: tuple[str, ...]
    evidence_ids: tuple[str, ...]


class RecommendationStrategy(Protocol):
    definition: RecommendationStrategyDefinition

    def discover(
        self, evidence: RecommendationStrategyInput
    ) -> tuple[StrategyCandidateGroup, ...]: ...


@dataclass(frozen=True, slots=True)
class HdbscanStrategyConfig:
    min_cluster_size: int = 2
    min_samples: int | None = 1
    allow_single_cluster: bool = False

    def __post_init__(self) -> None:
        if self.min_cluster_size < 2:
            raise ValueError("min_cluster_size must be at least 2")
        if self.min_samples is not None and self.min_samples < 1:
            raise ValueError("min_samples must be at least 1")


class IndependentEvidenceHdbscanStrategy:
    """Cluster every registered evidence channel independently, without fusion."""

    definition = RecommendationStrategyDefinition(
        strategy_id=DEFAULT_STRATEGY_ID,
        label="Independent evidence",
        description=(
            "Runs HDBSCAN separately for each evidence type and merges identical "
            "topic groups as consensus. No cross-evidence weighting is applied."
        ),
    )

    def __init__(
        self,
        config: HdbscanStrategyConfig,
        *,
        cluster_labels: ClusterLabels | None = None,
    ) -> None:
        self.config = config
        self._cluster_labels = cluster_labels or self._default_cluster_labels

    def discover(
        self, evidence: RecommendationStrategyInput
    ) -> tuple[StrategyCandidateGroup, ...]:
        memberships: dict[tuple[str, ...], set[str]] = {}
        for evidence_id in DISCOVERY_EVIDENCE_IDS:
            matrix = self._distance_matrix(
                evidence.topics,
                evidence.symmetric_scores,
                evidence_id,
            )
            labels = tuple(
                int(value) for value in self._cluster_labels(evidence_id, matrix)
            )
            if len(labels) != len(evidence.topics):
                raise ValueError("Discovery label count must match topic count")

            by_label: dict[int, list[str]] = {}
            for topic, label in zip(evidence.topics, labels, strict=True):
                if label < 0:
                    continue
                by_label.setdefault(label, []).append(topic)

            for members in by_label.values():
                canonical_members = tuple(sorted(members))
                if len(canonical_members) >= self.config.min_cluster_size:
                    memberships.setdefault(canonical_members, set()).add(evidence_id)

        return tuple(
            StrategyCandidateGroup(
                members=members,
                evidence_ids=tuple(
                    evidence_id
                    for evidence_id in DISCOVERY_EVIDENCE_IDS
                    if evidence_id in supporting_evidence
                ),
            )
            for members, supporting_evidence in memberships.items()
        )

    @staticmethod
    def _distance_matrix(
        topics: tuple[str, ...],
        scores: dict[tuple[str, str], dict[str, float | None]],
        evidence_id: str,
    ) -> DistanceMatrix:
        rows = []
        for left in topics:
            row = []
            for right in topics:
                if left == right:
                    row.append(0.0)
                    continue
                key = tuple(sorted((left, right)))
                value = scores[key].get(evidence_id)
                if value is None:
                    row.append(2.0)
                else:
                    similarity = max(-1.0, min(1.0, float(value)))
                    row.append(1.0 - similarity)
            rows.append(tuple(row))
        return tuple(rows)

    def _default_cluster_labels(
        self, evidence_id: str, matrix: DistanceMatrix
    ) -> Sequence[int]:
        del evidence_id
        if len(matrix) < self.config.min_cluster_size:
            return tuple(-1 for _ in matrix)
        return HDBSCAN(
            min_cluster_size=self.config.min_cluster_size,
            min_samples=self.config.min_samples,
            metric="precomputed",
            allow_single_cluster=self.config.allow_single_cluster,
        ).fit_predict(matrix)


STRATEGY_DEFINITIONS: tuple[RecommendationStrategyDefinition, ...] = (
    IndependentEvidenceHdbscanStrategy.definition,
)


def build_strategy(
    strategy_id: str,
    *,
    hdbscan_config: HdbscanStrategyConfig,
    cluster_labels: ClusterLabels | None = None,
) -> RecommendationStrategy:
    if strategy_id == DEFAULT_STRATEGY_ID:
        return IndependentEvidenceHdbscanStrategy(
            hdbscan_config,
            cluster_labels=cluster_labels,
        )
    raise ValueError(f"Unknown recommendation strategy: {strategy_id}")
