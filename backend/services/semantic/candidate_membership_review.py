"""Editable representation-specific membership feedback for candidates."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .candidate_confirmation import CandidateConfirmationSource, CandidateIdentity


class MembershipFeedbackKind(str, Enum):
    """How a reviewed topic relates to the original candidate suggestion."""

    KEPT = "KEPT"
    REMOVED = "REMOVED"
    ADDED = "ADDED"


class MembershipFeedbackPolarity(str, Enum):
    """Explicit class-membership evidence polarity."""

    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"


def _canonical_topics(value: tuple[str, ...], name: str) -> tuple[str, ...]:
    try:
        topics = tuple(value)
    except TypeError as exc:
        raise TypeError(f"{name} must be an iterable of topics") from exc
    if any(not isinstance(topic, str) or not topic.strip() for topic in topics):
        raise ValueError(f"{name} must contain non-empty strings")
    if len(set(topics)) != len(topics):
        raise ValueError(f"{name} must not contain duplicates")
    return tuple(sorted(topics))


@dataclass(frozen=True, slots=True)
class CandidateMembershipReview:
    """An explicit partition and correction of one candidate's membership."""

    identity: CandidateIdentity
    semantic_class_name: str
    kept_topics: tuple[str, ...]
    removed_topics: tuple[str, ...]
    added_topics: tuple[str, ...]
    source: CandidateConfirmationSource

    def __post_init__(self) -> None:
        if not isinstance(self.identity, CandidateIdentity):
            raise TypeError("identity must be a CandidateIdentity")
        if (
            not isinstance(self.semantic_class_name, str)
            or not self.semantic_class_name.strip()
        ):
            raise ValueError("semantic_class_name must be a non-empty string")
        if not isinstance(self.source, CandidateConfirmationSource):
            raise TypeError("source must be a CandidateConfirmationSource")

        kept = _canonical_topics(self.kept_topics, "kept_topics")
        removed = _canonical_topics(self.removed_topics, "removed_topics")
        added = _canonical_topics(self.added_topics, "added_topics")
        original = set(self.identity.member_topics)
        collections = (set(kept), set(removed), set(added))
        if any(
            collections[left] & collections[right]
            for left, right in ((0, 1), (0, 2), (1, 2))
        ):
            raise ValueError(
                "kept, removed, and added topics must be mutually disjoint"
            )
        if not set(kept) <= original:
            raise ValueError("kept topics must belong to the original candidate")
        if not set(removed) <= original:
            raise ValueError("removed topics must belong to the original candidate")
        if set(added) & original:
            raise ValueError("added topics must not belong to the original candidate")
        if set(kept) | set(removed) != original:
            raise ValueError(
                "kept and removed topics must partition the original candidate"
            )
        if not kept and not added:
            raise ValueError("at least one kept or added positive topic is required")
        object.__setattr__(self, "kept_topics", kept)
        object.__setattr__(self, "removed_topics", removed)
        object.__setattr__(self, "added_topics", added)

    @property
    def original_topics(self) -> tuple[str, ...]:
        return self.identity.member_topics

    @property
    def positive_topics(self) -> tuple[str, ...]:
        return tuple(sorted(self.kept_topics + self.added_topics))

    @property
    def negative_topics(self) -> tuple[str, ...]:
        return self.removed_topics

    @property
    def suggested_count(self) -> int:
        return len(self.original_topics)

    @property
    def kept_count(self) -> int:
        return len(self.kept_topics)

    @property
    def removed_count(self) -> int:
        return len(self.removed_topics)

    @property
    def added_count(self) -> int:
        return len(self.added_topics)

    @property
    def final_positive_count(self) -> int:
        return len(self.positive_topics)

    @property
    def suggestion_precision(self) -> float:
        return self.kept_count / self.suggested_count

    @property
    def suggestion_coverage_proxy(self) -> float:
        return self.kept_count / self.final_positive_count


@dataclass(frozen=True, slots=True)
class MembershipFeedbackEvidence:
    """Latest explicit membership evidence for one topic and class context."""

    topic: str
    semantic_class_name: str
    representation_name: str
    kind: MembershipFeedbackKind
    polarity: MembershipFeedbackPolarity
    source: CandidateConfirmationSource
    candidate_identity: CandidateIdentity


class MembershipFeedbackStore:
    """In-memory latest-state membership feedback without implicit history."""

    def __init__(self) -> None:
        self._evidence: dict[tuple[str, str, str], MembershipFeedbackEvidence] = {}

    def upsert(self, evidence: MembershipFeedbackEvidence) -> None:
        self._evidence[
            self._key(
                evidence.topic,
                evidence.semantic_class_name,
                evidence.representation_name,
            )
        ] = evidence

    def get(
        self, topic: str, semantic_class_name: str, representation_name: str
    ) -> MembershipFeedbackEvidence | None:
        return self._evidence.get(
            self._key(topic, semantic_class_name, representation_name)
        )

    def remove(
        self, topic: str, semantic_class_name: str, representation_name: str
    ) -> MembershipFeedbackEvidence | None:
        return self._evidence.pop(
            self._key(topic, semantic_class_name, representation_name), None
        )

    def all(self) -> tuple[MembershipFeedbackEvidence, ...]:
        return tuple(
            sorted(
                self._evidence.values(),
                key=lambda item: (
                    item.semantic_class_name,
                    item.representation_name,
                    item.topic,
                ),
            )
        )

    def __len__(self) -> int:
        return len(self._evidence)

    @staticmethod
    def _key(
        topic: str, semantic_class_name: str, representation_name: str
    ) -> tuple[str, str, str]:
        return topic, semantic_class_name, representation_name


class CandidateMembershipReviewProcessor:
    """Convert a review into deterministic positive and negative evidence."""

    def process(
        self, review: CandidateMembershipReview, store: MembershipFeedbackStore
    ) -> tuple[MembershipFeedbackEvidence, ...]:
        specifications = (
            *(
                (
                    topic,
                    MembershipFeedbackKind.KEPT,
                    MembershipFeedbackPolarity.POSITIVE,
                )
                for topic in review.kept_topics
            ),
            *(
                (
                    topic,
                    MembershipFeedbackKind.ADDED,
                    MembershipFeedbackPolarity.POSITIVE,
                )
                for topic in review.added_topics
            ),
            *(
                (
                    topic,
                    MembershipFeedbackKind.REMOVED,
                    MembershipFeedbackPolarity.NEGATIVE,
                )
                for topic in review.removed_topics
            ),
        )
        evidence = tuple(
            MembershipFeedbackEvidence(
                topic=topic,
                semantic_class_name=review.semantic_class_name,
                representation_name=review.identity.representation_name,
                kind=kind,
                polarity=polarity,
                source=review.source,
                candidate_identity=review.identity,
            )
            for topic, kind, polarity in specifications
        )
        for item in evidence:
            store.upsert(item)
        return evidence
