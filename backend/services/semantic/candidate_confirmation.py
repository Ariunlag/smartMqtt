"""Explicit trusted confirmation records for discovered UNKNOWN candidates."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .unknown_stream_discovery import UnknownClusterCandidate

_REPRESENTATION_NAMES = (
    "value_only",
    "key_only",
    "key_value",
    "schema",
    "numeric_key_only",
    "topic_key_value",
)


class CandidateConfirmationState(str, Enum):
    """Explicit outcomes for a discovered candidate."""

    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"


class CandidateConfirmationSource(str, Enum):
    """Trusted source that supplied a confirmation outcome."""

    HUMAN = "HUMAN"
    SYSTEM = "SYSTEM"


@dataclass(frozen=True, slots=True)
class CandidateIdentity:
    """Durable content identity for one representation-specific candidate."""

    representation_name: str
    member_topics: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.representation_name not in _REPRESENTATION_NAMES:
            raise ValueError(
                "representation_name must be one of the six representations"
            )
        try:
            topics = tuple(self.member_topics)
        except TypeError as exc:
            raise TypeError("member_topics must be an iterable of topics") from exc
        if not topics:
            raise ValueError("member_topics must not be empty")
        if any(not isinstance(topic, str) or not topic.strip() for topic in topics):
            raise ValueError("member_topics must contain non-empty strings")
        if len(set(topics)) != len(topics):
            raise ValueError("member_topics must not contain duplicates")
        object.__setattr__(self, "member_topics", tuple(sorted(topics)))

    @classmethod
    def from_candidate(cls, candidate: UnknownClusterCandidate) -> CandidateIdentity:
        """Create identity from discovery content, excluding local candidate index."""
        return cls(
            representation_name=candidate.representation_name,
            member_topics=candidate.member_topics,
        )


@dataclass(frozen=True, slots=True)
class CandidateConfirmation:
    """Explicit trusted confirmation or rejection for one candidate identity."""

    identity: CandidateIdentity
    state: CandidateConfirmationState
    source: CandidateConfirmationSource
    semantic_class_name: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.state, CandidateConfirmationState):
            raise TypeError("state must be a CandidateConfirmationState")
        if not isinstance(self.source, CandidateConfirmationSource):
            raise TypeError("source must be a CandidateConfirmationSource")
        if self.state is CandidateConfirmationState.CONFIRMED:
            if (
                not isinstance(self.semantic_class_name, str)
                or not self.semantic_class_name.strip()
            ):
                raise ValueError(
                    "semantic_class_name must be a non-empty string when confirmed"
                )
        elif self.semantic_class_name is not None:
            raise ValueError("semantic_class_name must be None when rejected")


class CandidateConfirmationStore:
    """In-memory latest-record store for explicit candidate feedback."""

    def __init__(self) -> None:
        self._confirmations: dict[CandidateIdentity, CandidateConfirmation] = {}

    def record(self, confirmation: CandidateConfirmation) -> None:
        """Insert or replace the confirmation for its candidate identity."""
        self._confirmations[confirmation.identity] = confirmation

    def get(self, identity: CandidateIdentity) -> CandidateConfirmation | None:
        """Return the latest confirmation for an identity, if present."""
        return self._confirmations.get(identity)

    def remove(self, identity: CandidateIdentity) -> CandidateConfirmation | None:
        """Remove and return a confirmation, or ``None`` when absent."""
        return self._confirmations.pop(identity, None)

    def all(self) -> tuple[CandidateConfirmation, ...]:
        """Return confirmations by representation then canonical member topics."""
        return tuple(
            sorted(
                self._confirmations.values(),
                key=lambda confirmation: (
                    confirmation.identity.representation_name,
                    confirmation.identity.member_topics,
                ),
            )
        )

    def __len__(self) -> int:
        """Return the count of unique candidate identities."""
        return len(self._confirmations)
