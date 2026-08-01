"""Atomic six-view prototype reconciliation after membership correction."""

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
class ReviewedPrototypeReconciliationResult:
    """Resulting six-view evidence after one atomic membership correction."""

    semantic_class_name: str
    positive_topics: tuple[str, ...]
    removed_topics: tuple[str, ...]
    changed_representations: tuple[str, ...]
    evidence: tuple[TrustedClassEvidence, ...]


class ReviewedPrototypeReconciler:
    """Rebuild changed prototypes from final members' current embeddings."""

    def apply(
        self,
        review: CandidateMembershipReview,
        unknown_pool: UnknownStreamPool,
        evidence_store: TrustedClassEvidenceStore,
    ) -> ReviewedPrototypeReconciliationResult:
        """Prepare and commit all changed replacements atomically."""
        result = self.prepare(review, unknown_pool, evidence_store)
        changed = set(result.changed_representations)
        for evidence in result.evidence:
            if evidence.representation_name in changed:
                evidence_store.upsert(evidence)
        return result

    def prepare(
        self,
        review: CandidateMembershipReview,
        unknown_pool: UnknownStreamPool,
        evidence_store: TrustedClassEvidenceStore,
    ) -> ReviewedPrototypeReconciliationResult:
        """Compute all replacements without mutating the evidence store."""
        prepared = []
        changed = []
        positive = set(review.positive_topics)
        removed = set(review.removed_topics)

        for representation_name in _REPRESENTATION_NAMES:
            existing = evidence_store.get(
                review.semantic_class_name,
                representation_name,
            )
            existing_topics = set(existing.member_topics) if existing else set()
            final_topics = tuple(sorted((existing_topics | positive) - removed))
            if not final_topics:
                raise ValueError(
                    f"Reconciliation for class '{review.semantic_class_name}', "
                    f"representation '{representation_name}' has no final members"
                )
            if existing is not None and final_topics == existing.member_topics:
                prepared.append(existing)
                continue

            vectors = []
            for topic in final_topics:
                entry = unknown_pool.get(topic)
                if entry is None:
                    raise ValueError(
                        f"Missing final-member topic '{topic}' for class "
                        f"'{review.semantic_class_name}', representation "
                        f"'{representation_name}'"
                    )
                vector = getattr(entry.embeddings, representation_name)
                vectors.append(
                    self._validate_vector(
                        vector,
                        review.semantic_class_name,
                        representation_name,
                        topic,
                    )
                )
            self._validate_dimensions(
                tuple(vectors),
                final_topics,
                review.semantic_class_name,
                representation_name,
            )
            try:
                centroid = StreamClassEngine.compute_centroid(vectors)
            except ValueError as exc:
                raise ValueError(
                    f"Could not rebuild class '{review.semantic_class_name}', "
                    f"representation '{representation_name}': {exc}"
                ) from exc
            prepared.append(
                TrustedClassEvidence(
                    semantic_class_name=review.semantic_class_name,
                    representation_name=representation_name,
                    centroid=centroid,
                    member_topics=final_topics,
                )
            )
            changed.append(representation_name)

        return ReviewedPrototypeReconciliationResult(
            semantic_class_name=review.semantic_class_name,
            positive_topics=review.positive_topics,
            removed_topics=review.removed_topics,
            changed_representations=tuple(changed),
            evidence=tuple(prepared),
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
    def _validate_dimensions(vectors, topics, class_name, representation_name):
        expected = len(vectors[0])
        for topic, vector in zip(topics, vectors, strict=True):
            if len(vector) != expected:
                raise ValueError(
                    f"Invalid vector for class '{class_name}', representation "
                    f"'{representation_name}', topic '{topic}': dimension "
                    f"{len(vector)} does not match {expected}"
                )
