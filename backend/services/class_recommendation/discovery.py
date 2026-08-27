"""System-derived recommended-class candidates over independent evidence.

Saved Classes are deliberately not consulted here. The discovery service prepares one
immutable evidence snapshot, then delegates candidate formation to a registered
strategy. Embedding generation and persistence remain independent of that strategy so
HDBSCAN, centroid/prototype, weighted, and learned approaches can be evaluated over
the same evidence without rematerializing vectors.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass

from .domain import (
    REPRESENTATION_CONTRACT_VERSION,
    Coverage,
    EvidenceScores,
    MatchedPairEvidence,
    PairEmbeddingRecord,
)
from .evidence import (
    DISCOVERY_EVIDENCE_IDS,
    EVIDENCE_CATALOG,
    PAIR_EVIDENCE_IDS,
    EvidenceDefinition,
)
from .matching import cosine
from .strategies import (
    DEFAULT_STRATEGY_ID,
    STRATEGY_DEFINITIONS,
    ClusterLabels,
    HdbscanStrategyConfig,
    RecommendationStrategyDefinition,
    RecommendationStrategyInput,
    TagValueCentroidStrategyConfig,
    build_strategy,
)

# Compatibility names retained for callers/tests while the source of truth lives in
# the evidence and strategy registries.
DISCOVERY_CHANNELS: tuple[str, ...] = DISCOVERY_EVIDENCE_IDS
RecommendedClassDiscoveryConfig = HdbscanStrategyConfig


@dataclass(frozen=True, slots=True)
class TopicComparisonEvidence:
    topic: str
    channel_scores: EvidenceScores
    coverage: Coverage
    matched_pairs: tuple[MatchedPairEvidence, ...]
    duplicate_pending: bool


@dataclass(frozen=True, slots=True)
class RecommendedClassCandidate:
    candidate_id: str
    candidate_version: int
    rank: int
    anchor_topic: str
    member_topics: tuple[str, ...]
    discovery_channels: tuple[str, ...]
    evidence: tuple[TopicComparisonEvidence, ...]


@dataclass(frozen=True, slots=True)
class RecommendedClassCandidateSet:
    candidates: tuple[RecommendedClassCandidate, ...]
    available_topics: tuple[str, ...]
    strategy: RecommendationStrategyDefinition
    strategy_catalog: tuple[RecommendationStrategyDefinition, ...] = STRATEGY_DEFINITIONS
    evidence_catalog: tuple[EvidenceDefinition, ...] = EVIDENCE_CATALOG


class TopicEvidenceMatcher:
    """Compare two topics without collapsing registered evidence channels.

    Pair identity stays intact. Candidate pairs only compete against reference pairs
    with the same source and datatype. A scalar compatibility is used only to make the
    one-to-one assignment deterministic; it is not returned as a recommendation
    confidence score.
    """

    @classmethod
    def compare(
        cls,
        *,
        candidate_topic: str,
        candidate_pairs: tuple[PairEmbeddingRecord, ...],
        candidate_stream: tuple[float, ...] | None,
        reference_topic: str,
        reference_pairs: tuple[PairEmbeddingRecord, ...],
        reference_stream: tuple[float, ...] | None,
        duplicate_pending: bool,
    ) -> TopicComparisonEvidence:
        candidates = []
        for pair in candidate_pairs:
            for reference in reference_pairs:
                left = pair.representation.identity
                right = reference.representation.identity
                if left.source != right.source or left.datatype != right.datatype:
                    continue
                scores = cls._scores(pair, reference)
                valid = scores.valid()
                compatibility = sum(value for _, value in valid) / len(valid)
                candidates.append((compatibility, pair, reference, scores))

        candidates.sort(
            key=lambda row: (
                -row[0],
                row[1].representation.identity,
                row[2].representation.identity,
            )
        )
        used_candidate = set()
        used_reference = set()
        matches = []
        for compatibility, pair, reference, scores in candidates:
            candidate_identity = pair.representation.identity
            reference_identity = reference.representation.identity
            if (
                candidate_identity in used_candidate
                or reference_identity in used_reference
            ):
                continue
            used_candidate.add(candidate_identity)
            used_reference.add(reference_identity)
            matches.append(
                MatchedPairEvidence(
                    candidate=candidate_identity,
                    prototype=reference_identity,
                    prototype_id=f"{reference_topic}:{reference_identity.value}",
                    scores=scores,
                    compatibility_score=compatibility,
                )
            )

        matches.sort(
            key=lambda item: (item.candidate, item.prototype, item.prototype_id)
        )
        pair_count = len(candidate_pairs)
        reference_count = len(reference_pairs)
        matched_count = len(matches)
        channels = cls._channel_scores(matches, candidate_stream, reference_stream)
        return TopicComparisonEvidence(
            topic=candidate_topic,
            channel_scores=channels,
            coverage=Coverage(
                candidate_pair_count=pair_count,
                class_prototype_count=reference_count,
                matched_pair_count=matched_count,
                candidate_coverage=matched_count / pair_count if pair_count else 0.0,
                prototype_coverage=(
                    matched_count / reference_count if reference_count else 0.0
                ),
            ),
            matched_pairs=tuple(matches),
            duplicate_pending=duplicate_pending,
        )

    @staticmethod
    def _scores(
        pair: PairEmbeddingRecord, reference: PairEmbeddingRecord
    ) -> EvidenceScores:
        values = {}
        for evidence_id in PAIR_EVIDENCE_IDS:
            left = pair.vector_for(evidence_id)
            right = reference.vector_for(evidence_id)
            if left is None or right is None:
                raise ValueError(
                    f"Pair evidence is missing required view '{evidence_id}'"
                )
            values[evidence_id] = cosine(left, right)
        return EvidenceScores.from_values(values)

    @staticmethod
    def _channel_scores(matches, candidate_stream, reference_stream) -> EvidenceScores:
        def mean(evidence_id: str) -> float | None:
            values = [
                value
                for match in matches
                if (value := match.scores.get(evidence_id)) is not None
            ]
            return sum(values) / len(values) if values else None

        values = {evidence_id: mean(evidence_id) for evidence_id in PAIR_EVIDENCE_IDS}
        context = None
        if candidate_stream is not None and reference_stream is not None:
            context = cosine(candidate_stream, reference_stream)
        values["stream_context"] = context
        return EvidenceScores.from_values(values)


class RecommendedClassDiscovery:
    """Prepare evidence once and delegate candidate formation to a strategy."""

    def __init__(
        self,
        *,
        metadata_store,
        pair_store,
        topic_embedding_store,
        identity_store,
        dupe_store,
        config: RecommendedClassDiscoveryConfig | None = None,
        centroid_config: TagValueCentroidStrategyConfig | None = None,
        cluster_labels: ClusterLabels | None = None,
        strategy_id: str = DEFAULT_STRATEGY_ID,
        candidate_store=None,
    ) -> None:
        self.metadata_store = metadata_store
        self.pair_store = pair_store
        self.topic_embedding_store = topic_embedding_store
        self.identity_store = identity_store
        self.dupe_store = dupe_store
        self.config = config or RecommendedClassDiscoveryConfig()
        self.centroid_config = centroid_config or TagValueCentroidStrategyConfig()
        self.cluster_labels = cluster_labels
        self.strategy_id = strategy_id
        self.candidate_store = candidate_store

    def discover(self, strategy_id: str | None = None) -> RecommendedClassCandidateSet:
        selected_strategy_id = strategy_id or self.strategy_id
        strategy = build_strategy(
            selected_strategy_id,
            hdbscan_config=self.config,
            centroid_config=self.centroid_config,
            cluster_labels=self.cluster_labels,
        )

        topics, versions, pairs_by_topic, streams = self._active_material()
        if len(topics) < 2:
            return RecommendedClassCandidateSet(
                candidates=(),
                available_topics=topics,
                strategy=strategy.definition,
            )

        comparisons: dict[tuple[str, str], TopicComparisonEvidence] = {}
        symmetric_scores: dict[tuple[str, str], dict[str, float | None]] = {}
        for left_index, left in enumerate(topics):
            for right in topics[left_index + 1 :]:
                forward = TopicEvidenceMatcher.compare(
                    candidate_topic=left,
                    candidate_pairs=pairs_by_topic[left],
                    candidate_stream=streams[left],
                    reference_topic=right,
                    reference_pairs=pairs_by_topic[right],
                    reference_stream=streams[right],
                    duplicate_pending=self.dupe_store.has_pending(left),
                )
                reverse = TopicEvidenceMatcher.compare(
                    candidate_topic=right,
                    candidate_pairs=pairs_by_topic[right],
                    candidate_stream=streams[right],
                    reference_topic=left,
                    reference_pairs=pairs_by_topic[left],
                    reference_stream=streams[left],
                    duplicate_pending=self.dupe_store.has_pending(right),
                )
                comparisons[(left, right)] = forward
                comparisons[(right, left)] = reverse
                symmetric_scores[(left, right)] = self._symmetric_channels(
                    forward.channel_scores, reverse.channel_scores
                )

        strategy_input = RecommendationStrategyInput(
            topics=topics,
            versions=versions,
            pairs_by_topic=pairs_by_topic,
            stream_vectors=streams,
            symmetric_scores=symmetric_scores,
        )
        groups = strategy.discover(strategy_input)

        candidates = []
        for group in groups:
            members = group.members
            anchor = members[0]
            evidence = tuple(
                comparisons[(topic, anchor)]
                if (topic, anchor) in comparisons
                else comparisons[(anchor, topic)]
                for topic in members
                if topic != anchor
            )
            candidate_id = self._candidate_id(
                members,
                strategy.definition.strategy_id,
            )
            evidence_snapshot = self._candidate_snapshot(
                anchor=anchor,
                members=members,
                discovery_channels=group.evidence_ids,
                evidence=evidence,
                versions=versions,
                strategy_id=strategy.definition.strategy_id,
            )
            candidate_version = 1
            if self.candidate_store is not None:
                candidate_version = self.candidate_store.persist_snapshot(
                    candidate_id=candidate_id,
                    strategy_id=strategy.definition.strategy_id,
                    member_topics=members,
                    discovery_evidence=group.evidence_ids,
                    evidence_snapshot=evidence_snapshot,
                )
            candidates.append(
                RecommendedClassCandidate(
                    candidate_id=candidate_id,
                    candidate_version=candidate_version,
                    rank=0,
                    anchor_topic=anchor,
                    member_topics=members,
                    discovery_channels=group.evidence_ids,
                    evidence=evidence,
                )
            )

        candidates.sort(
            key=lambda item: (
                -len(item.discovery_channels),
                -len(item.member_topics),
                item.member_topics,
            )
        )
        ranked = tuple(
            RecommendedClassCandidate(
                candidate_id=item.candidate_id,
                candidate_version=item.candidate_version,
                rank=index,
                anchor_topic=item.anchor_topic,
                member_topics=item.member_topics,
                discovery_channels=item.discovery_channels,
                evidence=item.evidence,
            )
            for index, item in enumerate(candidates, 1)
        )
        return RecommendedClassCandidateSet(
            candidates=ranked,
            available_topics=topics,
            strategy=strategy.definition,
        )

    def _active_material(self):
        topics = []
        versions = {}
        pairs_by_topic = {}
        streams = {}
        for row in self.metadata_store.all_topic_states():
            topic = row["canonical_topic"]
            if self.identity_store.is_duplicate_alias(topic):
                continue
            state = self.metadata_store.topic_state(topic)
            if (
                state is None
                or state.get("representation_contract_version")
                != REPRESENTATION_CONTRACT_VERSION
            ):
                continue
            pairs = tuple(self.pair_store.get_topic(topic))
            stream = self.topic_embedding_store.get(topic)
            stream_vector = (
                tuple(float(value) for value in stream["embedding"])
                if stream is not None
                else None
            )
            if not pairs and stream_vector is None:
                continue
            topics.append(topic)
            versions[topic] = int(state["representation_version"])
            pairs_by_topic[topic] = pairs
            streams[topic] = stream_vector
        ordered = tuple(sorted(topics))
        return (
            ordered,
            versions,
            {topic: pairs_by_topic[topic] for topic in ordered},
            {topic: streams[topic] for topic in ordered},
        )

    @staticmethod
    def _symmetric_channels(
        left: EvidenceScores, right: EvidenceScores
    ) -> dict[str, float | None]:
        result = {}
        for evidence_id in DISCOVERY_EVIDENCE_IDS:
            left_value = left.get(evidence_id)
            right_value = right.get(evidence_id)
            result[evidence_id] = (
                min(left_value, right_value)
                if left_value is not None and right_value is not None
                else None
            )
        return result

    @staticmethod
    def _candidate_snapshot(
        *,
        anchor: str,
        members: tuple[str, ...],
        discovery_channels: tuple[str, ...],
        evidence: tuple[TopicComparisonEvidence, ...],
        versions: dict[str, int],
        strategy_id: str,
    ) -> dict:
        return {
            "representation_contract_version": REPRESENTATION_CONTRACT_VERSION,
            "strategy_id": strategy_id,
            "anchor_topic": anchor,
            "member_topics": list(members),
            "member_representation_versions": {
                topic: versions[topic] for topic in members
            },
            "discovery_evidence": list(discovery_channels),
            "topic_evidence": [asdict(item) for item in evidence],
        }

    @staticmethod
    def _candidate_id(
        members: tuple[str, ...],
        strategy_id: str,
    ) -> str:
        """Stable identity for one strategy/member set, independent of evidence version."""
        payload = {
            "strategy": strategy_id,
            "members": list(members),
        }
        fingerprint = hashlib.sha256(
            json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        return str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"smartmqtt:recommended-class-candidate:{fingerprint}",
            )
        )
