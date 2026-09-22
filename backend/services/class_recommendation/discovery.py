"""System-derived recommended-class candidates over independent evidence.

Saved Classes are deliberately not consulted here. The discovery service prepares one
immutable evidence snapshot, then delegates candidate formation to a registered
strategy. Independent discovery happens before any cross-topic explanation matching,
so pair-matching averages cannot change candidate membership. Exact topic memberships
found by multiple evidence spaces may be merged by the strategy while near-matches
remain separate.
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
    StrategyEvidenceSupport,
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
    discovery_support: tuple[StrategyEvidenceSupport, ...]
    evidence: tuple[TopicComparisonEvidence, ...]


@dataclass(frozen=True, slots=True)
class RecommendedClassCandidateSet:
    candidates: tuple[RecommendedClassCandidate, ...]
    available_topics: tuple[str, ...]
    strategy: RecommendationStrategyDefinition
    strategy_catalog: tuple[RecommendationStrategyDefinition, ...] = (
        STRATEGY_DEFINITIONS
    )
    evidence_catalog: tuple[EvidenceDefinition, ...] = EVIDENCE_CATALOG


class TopicEvidenceMatcher:
    """Build post-discovery explanations for only the evidence that found a group.

    Pair evidence is aligned independently per discovery channel. A value-discovered
    group therefore explains only value matches, a key-discovered group only key
    matches, and so on. Exact memberships merged across multiple discovery channels
    keep a separate explanation for each channel. These explanations never change
    candidate membership.
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
        evidence_ids: tuple[str, ...] | None = None,
    ) -> TopicComparisonEvidence:
        selected = tuple(evidence_ids or DISCOVERY_EVIDENCE_IDS)
        unknown = set(selected) - set(DISCOVERY_EVIDENCE_IDS)
        if unknown:
            raise ValueError(
                "Unknown discovery evidence ids: " + ", ".join(sorted(unknown))
            )

        matches: list[MatchedPairEvidence] = []
        channel_values: dict[str, float | None] = {}
        matched_counts: list[int] = []

        for evidence_id in selected:
            if evidence_id == "stream_context":
                channel_values[evidence_id] = (
                    cosine(candidate_stream, reference_stream)
                    if candidate_stream is not None and reference_stream is not None
                    else None
                )
                continue

            channel_matches = cls._match_channel(
                evidence_id=evidence_id,
                candidate_pairs=candidate_pairs,
                reference_topic=reference_topic,
                reference_pairs=reference_pairs,
            )
            matches.extend(channel_matches)
            matched_counts.append(len(channel_matches))
            scores = [
                score
                for match in channel_matches
                if (score := match.scores.get(evidence_id)) is not None
            ]
            channel_values[evidence_id] = (
                sum(scores) / len(scores) if scores else None
            )

        pair_count = len(candidate_pairs)
        reference_count = len(reference_pairs)
        matched_count = max(matched_counts, default=0)

        return TopicComparisonEvidence(
            topic=candidate_topic,
            channel_scores=EvidenceScores.from_values(channel_values),
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
    def _match_channel(
        *,
        evidence_id: str,
        candidate_pairs: tuple[PairEmbeddingRecord, ...],
        reference_topic: str,
        reference_pairs: tuple[PairEmbeddingRecord, ...],
    ) -> list[MatchedPairEvidence]:
        candidates = []
        for pair in candidate_pairs:
            for reference in reference_pairs:
                left = pair.representation.identity
                right = reference.representation.identity
                if left.source != right.source or left.datatype != right.datatype:
                    continue

                left_vector = pair.vector_for(evidence_id)
                right_vector = reference.vector_for(evidence_id)
                if left_vector is None or right_vector is None:
                    continue

                score = cosine(left_vector, right_vector)
                candidates.append((score, pair, reference))

        candidates.sort(
            key=lambda row: (
                -row[0],
                row[1].representation.identity,
                row[2].representation.identity,
            )
        )

        used_candidate = set()
        used_reference = set()
        matches: list[MatchedPairEvidence] = []
        for score, pair, reference in candidates:
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
                    scores=EvidenceScores.from_values({evidence_id: score}),
                    compatibility_score=score,
                    candidate_text=pair.representation.text_for(evidence_id),
                    prototype_text=reference.representation.text_for(evidence_id),
                )
            )

        matches.sort(
            key=lambda item: (
                -item.compatibility_score,
                item.candidate,
                item.prototype,
                item.prototype_id,
            )
        )
        return matches


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

        topics, versions, pairs_by_topic, streams, pending_topics = (
            self._active_material()
        )
        if len(topics) < 2:
            return RecommendedClassCandidateSet(
                candidates=(),
                available_topics=topics,
                strategy=strategy.definition,
            )

        # Candidate membership is discovered directly from the raw evidence spaces.
        # No topic-level score averaging or pair alignment participates in grouping.
        strategy_input = RecommendationStrategyInput(
            topics=topics,
            versions=versions,
            pairs_by_topic=pairs_by_topic,
            stream_vectors=streams,
            symmetric_scores={},
        )
        groups = strategy.discover(strategy_input)

        candidates = []
        for group in groups:
            members = group.members
            anchor = members[0]

            # Explanations are calculated only after membership is fixed. The anchor
            # is a display/reference device, not a clustering center or winner.
            evidence = tuple(
                TopicEvidenceMatcher.compare(
                    candidate_topic=topic,
                    candidate_pairs=pairs_by_topic[topic],
                    candidate_stream=streams[topic],
                    reference_topic=anchor,
                    reference_pairs=pairs_by_topic[anchor],
                    reference_stream=streams[anchor],
                    duplicate_pending=topic in pending_topics,
                    evidence_ids=group.evidence_ids,
                )
                for topic in members
                if topic != anchor
            )
            candidate_id = self._candidate_id(
                members,
                strategy.definition.strategy_id,
                group.evidence_ids,
            )
            evidence_snapshot = self._candidate_snapshot(
                anchor=anchor,
                members=members,
                discovery_channels=group.evidence_ids,
                discovery_support=group.support,
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
                    discovery_support=group.support,
                    evidence=evidence,
                )
            )

        evidence_order = {
            evidence_id: index
            for index, evidence_id in enumerate(DISCOVERY_EVIDENCE_IDS)
        }
        candidates.sort(
            key=lambda item: (
                evidence_order.get(item.discovery_channels[0], len(evidence_order)),
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
        states = tuple(self.metadata_store.all_topic_states())
        state_topics = tuple(str(row["canonical_topic"]) for row in states)
        if hasattr(self.identity_store, "resolve_many"):
            identities = self.identity_store.resolve_many(state_topics)
        else:  # compatibility for lightweight test adapters
            identities = {
                topic: None if self.identity_store.is_duplicate_alias(topic) else topic
                for topic in state_topics
            }

        active_states = tuple(
            row
            for row in states
            if identities.get(str(row["canonical_topic"]), str(row["canonical_topic"]))
            == str(row["canonical_topic"])
            and row.get("representation_contract_version")
            == REPRESENTATION_CONTRACT_VERSION
        )
        selected_topics = tuple(
            sorted(str(row["canonical_topic"]) for row in active_states)
        )

        if hasattr(self.pair_store, "get_topics"):
            pairs_by_topic = self.pair_store.get_topics(selected_topics)
        else:
            pairs_by_topic = {
                topic: tuple(self.pair_store.get_topic(topic))
                for topic in selected_topics
            }

        if hasattr(self.topic_embedding_store, "get_many"):
            stream_rows = self.topic_embedding_store.get_many(selected_topics)
        else:
            stream_rows = {
                topic: self.topic_embedding_store.get(topic)
                for topic in selected_topics
            }

        if hasattr(self.dupe_store, "pending_topics"):
            pending_topics = set(self.dupe_store.pending_topics(selected_topics))
        else:
            pending_topics = {
                topic for topic in selected_topics if self.dupe_store.has_pending(topic)
            }

        versions = {
            str(row["canonical_topic"]): int(row["representation_version"])
            for row in active_states
        }
        topics = []
        streams = {}
        for topic in selected_topics:
            pairs = tuple(pairs_by_topic.get(topic, ()))
            stream = stream_rows.get(topic)
            stream_vector = (
                tuple(float(value) for value in stream["embedding"])
                if stream is not None
                else None
            )
            if not pairs and stream_vector is None:
                continue
            topics.append(topic)
            pairs_by_topic[topic] = pairs
            streams[topic] = stream_vector

        ordered = tuple(topics)
        active_set = set(ordered)
        return (
            ordered,
            {topic: versions[topic] for topic in ordered},
            {topic: pairs_by_topic[topic] for topic in ordered},
            {topic: streams[topic] for topic in ordered},
            pending_topics & active_set,
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
        discovery_support: tuple[StrategyEvidenceSupport, ...],
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
            "discovery_support": [asdict(item) for item in discovery_support],
            "topic_evidence": [asdict(item) for item in evidence],
        }

    @staticmethod
    def _candidate_id(
        members: tuple[str, ...],
        strategy_id: str,
        discovery_channels: tuple[str, ...],
    ) -> str:
        """Stable identity for one strategy/evidence/member set.

        The independent strategy merges only exact topic memberships and records every
        evidence space that found that membership. If one topic differs, the membership
        tuple differs and therefore remains a separate candidate.
        """
        payload = {
            "strategy": strategy_id,
            "discovery_evidence": list(discovery_channels),
            "members": list(members),
        }
        fingerprint = hashlib.sha256(
            json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode(
                "utf-8"
            )
        ).hexdigest()
        return str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"smartmqtt:recommended-class-candidate:{fingerprint}",
            )
        )
