"""Dependency-free quality and uncertainty metrics for RQ1 experiments."""

from __future__ import annotations

import math
import random
from dataclasses import asdict, dataclass
from typing import Literal

DecisionState = Literal["KNOWN", "UNCERTAIN", "UNKNOWN"]


@dataclass(frozen=True, slots=True)
class RQ1Prediction:
    stream_id: str
    source_kind: str
    expected_label: str
    expected_unknown: bool
    automated_state: DecisionState
    automated_label: str | None
    ranked_labels: tuple[str, ...]
    decision_reason: str
    top_similarity: float
    similarity_margin: float
    per_view_similarities: dict[str, dict[str, float]]
    per_view_top_candidate: dict[str, str]
    top1_votes: int
    decision_source: str = "AUTOMATED"
    authoritative_label: str | None = None


@dataclass(frozen=True, slots=True)
class ClassMetrics:
    precision: float
    recall: float
    f1: float
    support: int


@dataclass(frozen=True, slots=True)
class RQ1QualityMetrics:
    sample_count: int
    accuracy: float
    macro_precision: float
    macro_recall: float
    macro_f1: float
    per_class: dict[str, ClassMetrics]
    confusion_labels: tuple[str, ...]
    confusion_matrix: tuple[tuple[int, ...], ...]
    unknown_precision: float
    unknown_recall: float
    uncertain_rate: float
    coverage: float
    known_class_false_positive_rate: float
    top1_accuracy: float
    top3_accuracy: float
    mean_reciprocal_rank: float

    def as_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["confusion_labels"] = list(self.confusion_labels)
        result["confusion_matrix"] = [list(row) for row in self.confusion_matrix]
        return result


def compute_quality_metrics(
    predictions: tuple[RQ1Prediction, ...],
    *,
    authoritative: bool = False,
) -> RQ1QualityMetrics:
    """Compute classifier metrics, keeping human overrides explicitly separate."""
    if authoritative:
        actual = tuple(
            item.expected_label
            if item.decision_source == "HUMAN_CONFIRMED"
            else "UNKNOWN"
            if item.expected_unknown
            else item.expected_label
            for item in predictions
        )
        predicted = tuple(
            item.authoritative_label
            if item.decision_source == "HUMAN_CONFIRMED"
            and item.authoritative_label is not None
            else _automated_output(item)
            for item in predictions
        )
    else:
        actual = tuple(
            "UNKNOWN" if item.expected_unknown else item.expected_label
            for item in predictions
        )
        predicted = tuple(_automated_output(item) for item in predictions)
    labels = tuple(sorted(set(actual) | set(predicted), key=_label_order))
    confusion = tuple(
        tuple(
            sum(a == expected and p == observed for a, p in zip(actual, predicted))
            for observed in labels
        )
        for expected in labels
    )
    per_class: dict[str, ClassMetrics] = {}
    for label in labels:
        tp = sum(a == label and p == label for a, p in zip(actual, predicted))
        fp = sum(a != label and p == label for a, p in zip(actual, predicted))
        fn = sum(a == label and p != label for a, p in zip(actual, predicted))
        precision = _ratio(tp, tp + fp)
        recall = _ratio(tp, tp + fn)
        per_class[label] = ClassMetrics(
            precision,
            recall,
            _ratio(2 * precision * recall, precision + recall),
            sum(a == label for a in actual),
        )
    metric_classes = tuple(label for label in labels if label != "UNCERTAIN")
    unknown_tp = sum(
        a == "UNKNOWN" and p == "UNKNOWN" for a, p in zip(actual, predicted)
    )
    unknown_predicted = sum(p == "UNKNOWN" for p in predicted)
    unknown_actual = sum(a == "UNKNOWN" for a in actual)
    unseen_known = sum(
        a == "UNKNOWN" and p not in {"UNKNOWN", "UNCERTAIN"}
        for a, p in zip(actual, predicted)
    )
    known_items = tuple(item for item in predictions if not item.expected_unknown)
    ranks = tuple(
        _rank(item.expected_label, item.ranked_labels) for item in known_items
    )
    return RQ1QualityMetrics(
        sample_count=len(predictions),
        accuracy=_ratio(sum(a == p for a, p in zip(actual, predicted)), len(actual)),
        macro_precision=_mean(per_class[label].precision for label in metric_classes),
        macro_recall=_mean(per_class[label].recall for label in metric_classes),
        macro_f1=_mean(per_class[label].f1 for label in metric_classes),
        per_class=per_class,
        confusion_labels=labels,
        confusion_matrix=confusion,
        unknown_precision=_ratio(unknown_tp, unknown_predicted),
        unknown_recall=_ratio(unknown_tp, unknown_actual),
        uncertain_rate=_ratio(sum(p == "UNCERTAIN" for p in predicted), len(predicted)),
        coverage=_ratio(sum(p != "UNCERTAIN" for p in predicted), len(predicted)),
        known_class_false_positive_rate=_ratio(unseen_known, unknown_actual),
        top1_accuracy=_ratio(sum(rank == 1 for rank in ranks), len(ranks)),
        top3_accuracy=_ratio(sum(0 < rank <= 3 for rank in ranks), len(ranks)),
        mean_reciprocal_rank=_mean(1.0 / rank if rank else 0.0 for rank in ranks),
    )


def bootstrap_intervals(
    predictions: tuple[RQ1Prediction, ...],
    *,
    seed: int,
    repetitions: int,
) -> dict[str, dict[str, float]]:
    """Return percentile bootstrap intervals for major quality comparisons."""
    if repetitions < 1:
        raise ValueError("bootstrap repetitions must be positive")
    if not predictions:
        return {}
    randomizer = random.Random(seed)
    samples: dict[str, list[float]] = {
        "accuracy": [],
        "macro_f1": [],
        "unknown_recall": [],
    }
    for _ in range(repetitions):
        sample = tuple(randomizer.choice(predictions) for _ in predictions)
        metrics = compute_quality_metrics(sample)
        samples["accuracy"].append(metrics.accuracy)
        samples["macro_f1"].append(metrics.macro_f1)
        samples["unknown_recall"].append(metrics.unknown_recall)
    return {
        name: {
            "lower_95": _percentile(values, 0.025),
            "upper_95": _percentile(values, 0.975),
            "repetitions": repetitions,
        }
        for name, values in samples.items()
    }


def _automated_output(item: RQ1Prediction) -> str:
    if item.automated_state == "UNKNOWN":
        return "UNKNOWN"
    if item.automated_state == "UNCERTAIN":
        return "UNCERTAIN"
    return item.automated_label or "UNCERTAIN"


def _label_order(label: str) -> tuple[int, str]:
    return (1 if label in {"UNKNOWN", "UNCERTAIN"} else 0, label)


def _rank(expected: str, labels: tuple[str, ...]) -> int:
    try:
        return labels.index(expected) + 1
    except ValueError:
        return 0


def _ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def _mean(values) -> float:
    items = tuple(values)
    return math.fsum(items) / len(items) if items else 0.0


def _percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)
