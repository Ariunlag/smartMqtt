"""Atomic six-view prototype updates from reviewed positive membership."""

from __future__ import annotations

from dataclasses import dataclass

from .candidate_membership_review import CandidateMembershipReview
from .representation_embedder import RepresentationEmbeddings
from .stream_class import StreamClassEngine
from .trusted_class_evidence import (
    TrustedClassEvidence,
    TrustedClassEvidenceStore,
    TrustedClassEvidenceUpdater,
)
from .unknown_stream_pool import UnknownStreamPool

_REPRESENTATION_NAMES = tuple(RepresentationEmbeddings.__dataclass_fields__)


@dataclass(frozen=True, slots=True)
class ReviewedPrototypeUpdateResult:
    """Six resulting prototypes and the views changed by one review."""

    semantic_class_name: str
    positive_topics: tuple[str, ...]
    evidence: tuple[TrustedClassEvidence, ...]
    changed_representations: tuple[str, ...]


class ReviewedPrototypeUpdater:
    """Apply reviewed positive stream membership to all six independent views."""

    def apply(
        self,
        review: CandidateMembershipReview,
        unknown_pool: UnknownStreamPool,
        evidence_store: TrustedClassEvidenceStore,
    ) -> ReviewedPrototypeUpdateResult:
        """Prepare all six updates before atomically replacing store state."""
        entries = tuple(unknown_pool.get(topic) for topic in review.positive_topics)
        missing = tuple(
            topic
            for topic, entry in zip(review.positive_topics, entries, strict=True)
            if entry is None
        )
        if missing:
            raise ValueError(
                f"Missing positive topics for class '{review.semantic_class_name}': "
                + ", ".join(missing)
            )

        prepared = []
        changed = []
        for representation_name in _REPRESENTATION_NAMES:
            vectors = tuple(
                self._validate_vector(
                    getattr(entry.embeddings, representation_name),
                    review.semantic_class_name,
                    representation_name,
                    topic,
                )
                for topic, entry in zip(review.positive_topics, entries, strict=True)
            )
            self._validate_dimensions(
                vectors,
                review.positive_topics,
                review.semantic_class_name,
                representation_name,
            )
            existing = evidence_store.get(
                review.semantic_class_name,
                representation_name,
            )
            if existing is not None:
                self._validate_existing_dimension(
                    existing,
                    vectors[0],
                    review.semantic_class_name,
                    representation_name,
                )
            new_topic_vectors = tuple(
                (topic, vector)
                for topic, vector in zip(review.positive_topics, vectors, strict=True)
                if existing is None or topic not in existing.member_topics
            )
            if existing is not None and not new_topic_vectors:
                prepared.append(existing)
                continue

            if existing is None:
                centroid = StreamClassEngine.compute_centroid(
                    vector for _, vector in new_topic_vectors
                )
                member_topics = tuple(topic for topic, _ in new_topic_vectors)
            else:
                centroid = existing.centroid
                member_count = existing.member_count
                for topic, vector in new_topic_vectors:
                    try:
                        centroid = StreamClassEngine.update_centroid(
                            centroid,
                            member_count,
                            vector,
                        )
                    except ValueError as exc:
                        raise ValueError(
                            f"Invalid vector for class '{review.semantic_class_name}', "
                            f"representation '{representation_name}', topic "
                            f"'{topic}': {exc}"
                        ) from exc
                    member_count += 1
                member_topics = existing.member_topics + tuple(
                    topic for topic, _ in new_topic_vectors
                )
            prepared.append(
                TrustedClassEvidence(
                    semantic_class_name=review.semantic_class_name,
                    representation_name=representation_name,
                    centroid=centroid,
                    member_topics=member_topics,
                )
            )
            changed.append(representation_name)

        frozen_evidence = tuple(prepared)
        for evidence in frozen_evidence:
            evidence_store.upsert(evidence)
        return ReviewedPrototypeUpdateResult(
            semantic_class_name=review.semantic_class_name,
            positive_topics=review.positive_topics,
            evidence=frozen_evidence,
            changed_representations=tuple(changed),
        )

    @staticmethod
    def _validate_vector(vector, class_name, representation_name, topic):
        try:
            return TrustedClassEvidenceUpdater.validate_vector(
                vector,
                representation_name,
                topic,
            )
        except (TypeError, ValueError) as exc:
            raise type(exc)(
                f"Invalid vector for class '{class_name}', representation "
                f"'{representation_name}', topic '{topic}': {exc}"
            ) from exc

    @staticmethod
    def _validate_dimensions(
        vectors,
        topics,
        class_name,
        representation_name,
    ):
        expected = len(vectors[0])
        for topic, vector in zip(topics, vectors, strict=True):
            if len(vector) != expected:
                raise ValueError(
                    f"Invalid vector for class '{class_name}', representation "
                    f"'{representation_name}', topic '{topic}': dimension "
                    f"{len(vector)} does not match {expected}"
                )

    @staticmethod
    def _validate_existing_dimension(
        existing,
        vector,
        class_name,
        representation_name,
    ):
        if len(existing.centroid) != len(vector):
            raise ValueError(
                f"Invalid vector for class '{class_name}', representation "
                f"'{representation_name}': dimension {len(vector)} does not match "
                f"existing prototype dimension {len(existing.centroid)}"
            )
