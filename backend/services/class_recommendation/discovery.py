"""System-derived recommended-class candidates with evidence-first explanations.

Saved Classes are deliberately not consulted here. This module discovers candidate
topic groups from current pair-level evidence and the shared stream-context vector.
Each registered evidence channel is clustered independently; exact candidate
memberships that appear in multiple channels are merged as consensus evidence
without averaging the channels into one user-facing score.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Callable, Sequence

from sklearn.cluster import HDBSCAN

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

# Compatibility name for callers/tests while the source of truth is the registry.
DISCOVERY_CHANNELS: tuple[str, ...] = DISCOVERY_EVIDENCE_IDS

ClusterLabels = Callable[[str, tuple[tuple[float, ...], ...]], Sequence[int]]


@dataclass(frozen=True, slots=True)
class RecommendedClassDiscoveryConfig:
    min_cluster_size: int = 2
    min_samples: int | None = 1
    allow_single_cluster: bool = False

    def __post_init__(self) -> None:
        if self.min_cluster_size < 2:
            raise ValueError("min_cluster_size must be at least 2")
        if self.min_samples is not None and self.min_samples < 1:
            raise ValueError("min_samples must be at least 1")


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
    rank: int
    anchor_topic: str
    member_topics: tuple[str, ...]
    discovery_channels: tuple[str, ...]
    evidence: tuple[TopicComparisonEvidence, ...]


@dataclass(frozen=True, slots=True)
class RecommendedClassCandidateSet:
    candidates: tuple[RecommendedClassCandidate, ...]
    available_topics: tuple[str, ...]
    evidence_catalog: tuple[EvidenceDefinition, ...] = EVIDENCE_CATALOG


class TopicEvidenceMatcher:
    """Compare two topics without collapsing registered evidence channels.

    Pair identity stays intact. Candidate pairs only compete against reference
    pairs with the same source and datatype. A scalar compatibility is used only
    to make the one-to-one assignment deterministic; it is not returned as a class
    recommendation score.
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
    """Discover system candidates independently of user-created Saved Classes."""

    def __init__(
        self,
        *,
        metadata_store,
        pair_store,
        topic_embedding_store,
        identity_store,
        dupe_store,
        config: RecommendedClassDiscoveryConfig | None = None,
        cluster_labels: ClusterLabels | None = None,
    ) -> None:
        self.metadata_store = metadata_store
        self.pair_store = pair_store
        self.topic_embedding_store = topic_embedding_store
        self.identity_store = identity_store
        self.dupe_store = dupe_store
        self.config = config or RecommendedClassDiscoveryConfig()
        self._cluster_labels = cluster_labels or self._default_cluster_labels

    def discover(self) -> RecommendedClassCandidateSet:
        topics, versions, pairs_by_topic, streams = self._active_material()
        if len(topics) < self.config.min_cluster_size:
            return RecommendedClassCandidateSet((), topics)

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

        memberships: dict[tuple[str, ...], set[str]] = {}
        for channel in DISCOVERY_EVIDENCE_IDS:
            matrix = self._distance_matrix(topics, symmetric_scores, channel)
            labels = tuple(int(value) for value in self._cluster_labels(channel, matrix))
            if len(labels) != len(topics):
                raise ValueError("Discovery label count must match topic count")
            by_label: dict[int, list[str]] = {}
            for topic, label in zip(topics, labels, strict=True):
                if label < 0:
                    continue
                by_label.setdefault(label, []).append(topic)
            for members in by_label.values():
                canonical_members = tuple(sorted(members))
                if len(canonical_members) >= self.config.min_cluster_size:
                    memberships.setdefault(canonical_members, set()).add(channel)

        candidates = []
        for members, channels in memberships.items():
            anchor = members[0]
            evidence = tuple(
                comparisons[(topic, anchor)]
                if (topic, anchor) in comparisons
                else comparisons[(anchor, topic)]
                for topic in members
                if topic != anchor
            )
            candidate_id = self._candidate_id(members, versions)
            candidates.append(
                RecommendedClassCandidate(
                    candidate_id=candidate_id,
                    rank=0,
                    anchor_topic=anchor,
                    member_topics=members,
                    discovery_channels=tuple(
                        channel
                        for channel in DISCOVERY_EVIDENCE_IDS
                        if channel in channels
                    ),
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
                rank=index,
                anchor_topic=item.anchor_topic,
                member_topics=item.member_topics,
                discovery_channels=item.discovery_channels,
                evidence=item.evidence,
            )
            for index, item in enumerate(candidates, 1)
        )
        return RecommendedClassCandidateSet(ranked, topics)

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
        for channel in DISCOVERY_EVIDENCE_IDS:
            left_value = left.get(channel)
            right_value = right.get(channel)
            result[channel] = (
                min(left_value, right_value)
                if left_value is not None and right_value is not None
                else None
            )
        return result

    @staticmethod
    def _distance_matrix(
        topics: tuple[str, ...],
        scores: dict[tuple[str, str], dict[str, float | None]],
        channel: str,
    ) -> tuple[tuple[float, ...], ...]:
        rows = []
        for left in topics:
            row = []
            for right in topics:
                if left == right:
                    row.append(0.0)
                    continue
                key = tuple(sorted((left, right)))
                value = scores[key].get(channel)
                if value is None:
                    row.append(2.0)
                else:
                    similarity = max(-1.0, min(1.0, float(value)))
                    row.append(1.0 - similarity)
            rows.append(tuple(row))
        return tuple(rows)

    def _default_cluster_labels(
        self, channel: str, matrix: tuple[tuple[float, ...], ...]
    ) -> Sequence[int]:
        del channel
        if len(matrix) < self.config.min_cluster_size:
            return tuple(-1 for _ in matrix)
        return HDBSCAN(
            min_cluster_size=self.config.min_cluster_size,
            min_samples=self.config.min_samples,
            metric="precomputed",
            allow_single_cluster=self.config.allow_single_cluster,
        ).fit_predict(matrix)

    @staticmethod
    def _candidate_id(
        members: tuple[str, ...], versions: dict[str, int]
    ) -> str:
        payload = {
            "contract": REPRESENTATION_CONTRACT_VERSION,
            "members": [(topic, versions[topic]) for topic in members],
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
