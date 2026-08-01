"""Configurable open-world decisions over multi-view consensus evidence."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from numbers import Real

from .multi_view_consensus import (
    MultiViewConsensusResult,
    RepresentationClassConsensus,
)


class SemanticClassDecisionState(str, Enum):
    """Open-world semantic class decision states."""

    KNOWN = "KNOWN"
    UNCERTAIN = "UNCERTAIN"
    UNKNOWN = "UNKNOWN"


class SemanticClassDecisionReason(str, Enum):
    """Deterministic reasons explaining a semantic class decision."""

    NO_KNOWN_CLASSES = "NO_KNOWN_CLASSES"
    ALL_CLASSES_BLOCKED = "ALL_CLASSES_BLOCKED"
    BELOW_UNKNOWN_SIMILARITY = "BELOW_UNKNOWN_SIMILARITY"
    INSUFFICIENT_TOP1_VOTES = "INSUFFICIENT_TOP1_VOTES"
    BELOW_KNOWN_SIMILARITY = "BELOW_KNOWN_SIMILARITY"
    INSUFFICIENT_SIMILARITY_MARGIN = "INSUFFICIENT_SIMILARITY_MARGIN"
    KNOWN_CRITERIA_MET = "KNOWN_CRITERIA_MET"


@dataclass(frozen=True, slots=True)
class SemanticClassDecisionConfig:
    """Explicit thresholds for the deterministic open-world policy."""

    known_min_top1_votes: int
    known_min_mean_similarity: float
    known_min_similarity_margin: float
    unknown_max_mean_similarity: float

    def __post_init__(self) -> None:
        if isinstance(self.known_min_top1_votes, bool) or not isinstance(
            self.known_min_top1_votes, int
        ):
            raise TypeError("known_min_top1_votes must be an integer from 1 through 6")
        if not 1 <= self.known_min_top1_votes <= 6:
            raise ValueError("known_min_top1_votes must be from 1 through 6")

        self._validate_threshold(
            "known_min_mean_similarity",
            self.known_min_mean_similarity,
            -1.0,
            1.0,
        )
        self._validate_threshold(
            "unknown_max_mean_similarity",
            self.unknown_max_mean_similarity,
            -1.0,
            1.0,
        )
        self._validate_threshold(
            "known_min_similarity_margin",
            self.known_min_similarity_margin,
            0.0,
            2.0,
        )
        if self.unknown_max_mean_similarity > self.known_min_mean_similarity:
            raise ValueError(
                "unknown_max_mean_similarity must be less than or equal to "
                "known_min_mean_similarity"
            )

    @staticmethod
    def _validate_threshold(
        name: str,
        value: float,
        minimum: float,
        maximum: float,
    ) -> None:
        if isinstance(value, bool) or not isinstance(value, Real):
            raise TypeError(f"{name} must be a real, finite value")
        if not math.isfinite(value):
            raise ValueError(f"{name} must be finite")
        if not minimum <= value <= maximum:
            raise ValueError(f"{name} must be within [{minimum:g}, {maximum:g}]")


@dataclass(frozen=True, slots=True)
class SemanticClassDecision:
    """An explainable decision that retains its consensus candidates."""

    state: SemanticClassDecisionState
    candidate: RepresentationClassConsensus | None
    runner_up: RepresentationClassConsensus | None
    similarity_margin: float | None
    reasons: tuple[SemanticClassDecisionReason, ...]


class SemanticClassDecisionPolicy:
    """Apply explicit open-world thresholds to consensus evidence."""

    def __init__(self, config: SemanticClassDecisionConfig):
        self.config = config

    def decide(self, consensus: MultiViewConsensusResult) -> SemanticClassDecision:
        """Return KNOWN, UNCERTAIN, or UNKNOWN without assigning a class."""
        if not consensus.classes:
            return SemanticClassDecision(
                state=SemanticClassDecisionState.UNKNOWN,
                candidate=None,
                runner_up=None,
                similarity_margin=None,
                reasons=(SemanticClassDecisionReason.NO_KNOWN_CLASSES,),
            )

        candidate = consensus.classes[0]
        runner_up = consensus.classes[1] if len(consensus.classes) > 1 else None
        similarity_margin = (
            candidate.mean_similarity - runner_up.mean_similarity
            if runner_up is not None
            else None
        )

        if candidate.mean_similarity <= self.config.unknown_max_mean_similarity:
            return SemanticClassDecision(
                state=SemanticClassDecisionState.UNKNOWN,
                candidate=candidate,
                runner_up=runner_up,
                similarity_margin=similarity_margin,
                reasons=(SemanticClassDecisionReason.BELOW_UNKNOWN_SIMILARITY,),
            )

        reasons: list[SemanticClassDecisionReason] = []
        if candidate.top1_votes < self.config.known_min_top1_votes:
            reasons.append(SemanticClassDecisionReason.INSUFFICIENT_TOP1_VOTES)
        if candidate.mean_similarity < self.config.known_min_mean_similarity:
            reasons.append(SemanticClassDecisionReason.BELOW_KNOWN_SIMILARITY)
        if (
            similarity_margin is not None
            and similarity_margin < self.config.known_min_similarity_margin
        ):
            reasons.append(SemanticClassDecisionReason.INSUFFICIENT_SIMILARITY_MARGIN)

        if reasons:
            return SemanticClassDecision(
                state=SemanticClassDecisionState.UNCERTAIN,
                candidate=candidate,
                runner_up=runner_up,
                similarity_margin=similarity_margin,
                reasons=tuple(reasons),
            )

        return SemanticClassDecision(
            state=SemanticClassDecisionState.KNOWN,
            candidate=candidate,
            runner_up=runner_up,
            similarity_margin=similarity_margin,
            reasons=(SemanticClassDecisionReason.KNOWN_CRITERIA_MET,),
        )
