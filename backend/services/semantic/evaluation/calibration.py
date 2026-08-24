"""Leakage-free Pareto calibration of explicit decision-threshold grids."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from itertools import product

from ..multi_view_consensus import MultiViewConsensusResult
from ..semantic_class_decision import (
    SemanticClassDecisionConfig,
    SemanticClassDecisionPolicy,
    SemanticClassDecisionState,
)


class SemanticCalibrationSplit(str, Enum):
    REFERENCE = "REFERENCE"
    CALIBRATION = "CALIBRATION"
    TEST = "TEST"


@dataclass(frozen=True, slots=True)
class SemanticDecisionThresholdGrid:
    known_min_top1_votes: tuple[int, ...]
    known_min_mean_similarity: tuple[float, ...]
    known_min_similarity_margin: tuple[float, ...]
    unknown_max_mean_similarity: tuple[float, ...]

    def configs(self) -> tuple[SemanticClassDecisionConfig, ...]:
        valid = []
        for values in product(
            self.known_min_top1_votes,
            self.known_min_mean_similarity,
            self.known_min_similarity_margin,
            self.unknown_max_mean_similarity,
        ):
            try:
                valid.append(SemanticClassDecisionConfig(*values))
            except (TypeError, ValueError):
                continue
        return tuple(sorted(set(valid), key=_config_key))


@dataclass(frozen=True, slots=True)
class SemanticCalibrationEvidence:
    """Reusable calibration-only consensus evidence and explicit ground truth."""

    expected_class_name: str
    is_unseen_class: bool
    consensus: MultiViewConsensusResult
    split: SemanticCalibrationSplit = SemanticCalibrationSplit.CALIBRATION

    def __post_init__(self) -> None:
        if self.split is not SemanticCalibrationSplit.CALIBRATION:
            raise ValueError("calibration evidence must have CALIBRATION split")


@dataclass(frozen=True, slots=True)
class SemanticCalibrationMetrics:
    known_top1_accuracy: float
    known_macro_f1: float
    unknown_precision: float
    unknown_recall: float
    false_unknown_rate: float
    known_count: int
    unseen_count: int


@dataclass(frozen=True, slots=True)
class SemanticCalibrationCandidate:
    config: SemanticClassDecisionConfig
    metrics: SemanticCalibrationMetrics


@dataclass(frozen=True, slots=True)
class SemanticCalibrationResult:
    all_candidates: tuple[SemanticCalibrationCandidate, ...]
    pareto_frontier: tuple[SemanticCalibrationCandidate, ...]


class SemanticThresholdCalibrator:
    """Evaluate only supplied calibration evidence; TEST data is never accepted."""

    def calibrate(
        self,
        calibration_evidence: tuple[SemanticCalibrationEvidence, ...],
        grid: SemanticDecisionThresholdGrid,
    ) -> SemanticCalibrationResult:
        evidence = tuple(calibration_evidence)
        candidates = tuple(
            SemanticCalibrationCandidate(config, self._metrics(evidence, config))
            for config in grid.configs()
        )
        return SemanticCalibrationResult(
            all_candidates=candidates,
            pareto_frontier=tuple(
                candidate
                for candidate in candidates
                if not any(
                    other is not candidate and _dominates(other, candidate)
                    for other in candidates
                )
            ),
        )

    @staticmethod
    def _metrics(evidence, config):
        decisions = [
            SemanticClassDecisionPolicy(config).decide(item.consensus)
            for item in evidence
        ]
        known = [
            (item, decision)
            for item, decision in zip(evidence, decisions, strict=True)
            if not item.is_unseen_class
        ]
        unseen = [
            (item, decision)
            for item, decision in zip(evidence, decisions, strict=True)
            if item.is_unseen_class
        ]
        correct = sum(
            decision.state is SemanticClassDecisionState.KNOWN
            and decision.class_name == item.expected_class_name
            for item, decision in known
        )
        unknown = [
            (item, decision)
            for item, decision in zip(evidence, decisions, strict=True)
            if decision.state is SemanticClassDecisionState.UNKNOWN
        ]
        tp = sum(item.is_unseen_class for item, _ in unknown)
        labels = sorted({item.expected_class_name for item, _ in known})
        f1 = []
        for label in labels:
            true_positive = sum(
                item.expected_class_name == label
                and decision.state is SemanticClassDecisionState.KNOWN
                and decision.class_name == label
                for item, decision in known
            )
            false_positive = sum(
                item.expected_class_name != label
                and decision.state is SemanticClassDecisionState.KNOWN
                and decision.class_name == label
                for item, decision in known
            )
            false_negative = sum(
                item.expected_class_name == label
                and not (
                    decision.state is SemanticClassDecisionState.KNOWN
                    and decision.class_name == label
                )
                for item, decision in known
            )
            f1.append(
                0.0
                if 2 * true_positive + false_positive + false_negative == 0
                else 2
                * true_positive
                / (2 * true_positive + false_positive + false_negative)
            )
        return SemanticCalibrationMetrics(
            correct / len(known) if known else 0.0,
            sum(f1) / len(f1) if f1 else 0.0,
            tp / len(unknown) if unknown else 0.0,
            tp / len(unseen) if unseen else 0.0,
            sum(not item.is_unseen_class for item, _ in unknown) / len(known)
            if known
            else 0.0,
            len(known),
            len(unseen),
        )


def _config_key(config):
    return (
        config.known_min_top1_votes,
        config.known_min_mean_similarity,
        config.known_min_similarity_margin,
        config.unknown_max_mean_similarity,
    )


def _dominates(left, right):
    a, b = left.metrics, right.metrics
    no_worse = (
        a.known_macro_f1 >= b.known_macro_f1
        and a.unknown_precision >= b.unknown_precision
        and a.unknown_recall >= b.unknown_recall
        and a.false_unknown_rate <= b.false_unknown_rate
    )
    better = (
        a.known_macro_f1 > b.known_macro_f1
        or a.unknown_precision > b.unknown_precision
        or a.unknown_recall > b.unknown_recall
        or a.false_unknown_rate < b.false_unknown_rate
    )
    return no_worse and better
