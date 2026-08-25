"""Transparent deterministic pair-to-prototype matching and ranking."""

from __future__ import annotations

import math
import uuid
from collections.abc import Iterable

from .domain import (
    ALGORITHM_VERSION,
    ChannelScores,
    ClassPairPrototype,
    ClassProfile,
    ClassRecommendation,
    Coverage,
    MatchedPairEvidence,
    PairEmbeddingRecord,
    PairIdentity,
    PairViewScores,
)


def cosine(left: Iterable[float], right: Iterable[float]) -> float:
    a = tuple(float(value) for value in left)
    b = tuple(float(value) for value in right)
    if len(a) != len(b) or not a:
        raise ValueError("Cosine vectors must have the same non-zero dimension")
    if not all(math.isfinite(value) for value in (*a, *b)):
        raise ValueError("Cosine vectors must be finite")
    denominator = math.sqrt(sum(value * value for value in a)) * math.sqrt(
        sum(value * value for value in b)
    )
    if denominator == 0:
        return 0.0
    return sum(x * y for x, y in zip(a, b, strict=True)) / denominator


def centroid(vectors: Iterable[Iterable[float]]) -> tuple[float, ...]:
    rows = tuple(tuple(float(value) for value in vector) for vector in vectors)
    if not rows:
        raise ValueError("Cannot compute an empty centroid")
    dimension = len(rows[0])
    if not dimension or any(len(row) != dimension for row in rows):
        raise ValueError("Centroid vectors must have one non-zero dimension")
    result = tuple(
        sum(row[index] for row in rows) / len(rows) for index in range(dimension)
    )
    if not all(math.isfinite(value) for value in result):
        raise ValueError("Centroid must be finite")
    return result


class PairClassMatcher:
    """Greedy maximum-score one-to-one matching with stable identity ties."""

    @classmethod
    def recommend(
        cls,
        *,
        canonical_topic: str,
        original_topic: str,
        topic_version: int,
        pairs: tuple[PairEmbeddingRecord, ...],
        stream_context: tuple[float, ...] | None,
        profile: ClassProfile,
        duplicate_pending: bool,
        rank: int = 0,
    ) -> ClassRecommendation:
        candidates = []
        for pair in pairs:
            for prototype in profile.pair_prototypes:
                scores = cls._scores(pair, prototype)
                valid = scores.valid()
                compatibility = sum(value for _, value in valid) / len(valid)
                candidates.append((compatibility, pair, prototype, scores))
        candidates.sort(
            key=lambda row: (
                -row[0],
                row[1].representation.identity,
                row[2].identity,
                row[2].prototype_id,
            )
        )
        used_pairs: set[PairIdentity] = set()
        used_prototypes: set[str] = set()
        matches = []
        for compatibility, pair, prototype, scores in candidates:
            pair_id = pair.representation.identity
            if pair_id in used_pairs or prototype.prototype_id in used_prototypes:
                continue
            used_pairs.add(pair_id)
            used_prototypes.add(prototype.prototype_id)
            matches.append(
                MatchedPairEvidence(
                    candidate=pair_id,
                    prototype=prototype.identity,
                    prototype_id=prototype.prototype_id,
                    scores=scores,
                    compatibility_score=compatibility,
                )
            )
        matches.sort(
            key=lambda item: (item.candidate, item.prototype, item.prototype_id)
        )
        channels = cls._channel_scores(matches, stream_context, profile)
        valid_channels = channels.valid()
        overall = (
            sum(value for _, value in valid_channels) / len(valid_channels)
            if valid_channels
            else 0.0
        )
        pair_count = len(pairs)
        prototype_count = len(profile.pair_prototypes)
        matched_count = len(matches)
        recommendation_identity = "\0".join(
            (
                canonical_topic,
                str(topic_version),
                profile.class_id,
                str(profile.profile_version),
                ALGORITHM_VERSION,
            )
        )
        return ClassRecommendation(
            recommendation_id=str(
                uuid.uuid5(uuid.NAMESPACE_URL, f"smartmqtt:{recommendation_identity}")
            ),
            canonical_topic=canonical_topic,
            original_topic=original_topic,
            class_id=profile.class_id,
            class_name=profile.class_name,
            rank=rank,
            overall_score=overall,
            channel_scores=channels,
            valid_channels=tuple(name for name, _ in valid_channels),
            coverage=Coverage(
                candidate_pair_count=pair_count,
                class_prototype_count=prototype_count,
                matched_pair_count=matched_count,
                candidate_coverage=matched_count / pair_count if pair_count else 0.0,
                prototype_coverage=(
                    matched_count / prototype_count if prototype_count else 0.0
                ),
            ),
            matched_pairs=tuple(matches),
            unmatched_candidate_pairs=tuple(
                sorted(
                    pair.representation.identity
                    for pair in pairs
                    if pair.representation.identity not in used_pairs
                )
            ),
            unmatched_prototypes=tuple(
                sorted(
                    prototype.identity
                    for prototype in profile.pair_prototypes
                    if prototype.prototype_id not in used_prototypes
                )
            ),
            class_profile_version=profile.profile_version,
            topic_representation_version=topic_version,
            duplicate_pending=duplicate_pending,
        )

    @staticmethod
    def _scores(
        pair: PairEmbeddingRecord, prototype: ClassPairPrototype
    ) -> PairViewScores:
        def score(name):
            pair_vector = pair.vector_for(name)
            prototype_vector = prototype.centroid_for(name)
            if pair_vector is None or prototype_vector is None:
                return None
            return cosine(pair_vector, prototype_vector)

        required = {
            name: score(name) for name in ("key", "value", "key_value", "schema")
        }
        if any(value is None for value in required.values()):
            raise ValueError("Pair and prototype are missing a required embedding view")
        return PairViewScores(
            key=required["key"],
            value=required["value"],
            key_value=required["key_value"],
            schema=required["schema"],
            numeric_key=score("numeric_key"),
        )

    @staticmethod
    def _channel_scores(matches, stream_context, profile) -> ChannelScores:
        def mean(name: str) -> float | None:
            values = [
                value
                for match in matches
                if (value := getattr(match.scores, name)) is not None
            ]
            return sum(values) / len(values) if values else None

        context_score = None
        if stream_context is not None and profile.stream_context_centroid is not None:
            context_score = cosine(stream_context, profile.stream_context_centroid)
        return ChannelScores(
            key=mean("key"),
            value=mean("value"),
            key_value=mean("key_value"),
            schema=mean("schema"),
            numeric_key=mean("numeric_key"),
            stream_context=context_score,
        )
