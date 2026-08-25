"""Reproducible RQ1 benchmark runner, costs, and machine-readable artifacts."""

from __future__ import annotations

import csv
import json
import math
import statistics
import subprocess
import time
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from services.embedding.base_model import BaseEmbeddingModel

from ..stream_class import StreamClassEngine
from .rq1_dataset import RQ1Dataset, RQ1SourceKind, RQ1Split
from .rq1_metrics import (
    RQ1Prediction,
    bootstrap_intervals,
    compute_quality_metrics,
)
from .rq1_representations import (
    RQ1RepresentationBuilder,
    RQ1RepresentationConfig,
    RQ1Variant,
    fuse_vectors,
)

ConsensusMode = Literal["SINGLE", "EQUAL_VOTE", "SIMILARITY_AVERAGE", "STATIC_WEIGHTS"]


@dataclass(frozen=True, slots=True)
class RQ1DecisionConfig:
    """Evaluation-only open-world thresholds; never production defaults."""

    known_min_similarity: float = 0.55
    known_min_margin: float = 0.0
    unknown_max_similarity: float = 0.15

    def __post_init__(self) -> None:
        values = (
            self.known_min_similarity,
            self.known_min_margin,
            self.unknown_max_similarity,
        )
        if any(not math.isfinite(value) for value in values):
            raise ValueError("decision thresholds must be finite")
        if not -1.0 <= self.unknown_max_similarity <= 1.0:
            raise ValueError("unknown_max_similarity must be within [-1, 1]")
        if not -1.0 <= self.known_min_similarity <= 1.0:
            raise ValueError("known_min_similarity must be within [-1, 1]")
        if not 0.0 <= self.known_min_margin <= 2.0:
            raise ValueError("known_min_margin must be within [0, 2]")
        if self.unknown_max_similarity > self.known_min_similarity:
            raise ValueError("unknown threshold cannot exceed known threshold")


@dataclass(frozen=True, slots=True)
class RQ1Condition:
    name: str
    variants: tuple[RQ1Variant, ...]
    consensus: ConsensusMode = "SINGLE"
    static_weights: tuple[tuple[RQ1Variant, float], ...] = ()

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.variants:
            raise ValueError("condition name and variants are required")
        if len(set(self.variants)) != len(self.variants):
            raise ValueError("condition variants must be unique")
        if self.consensus not in {
            "SINGLE",
            "EQUAL_VOTE",
            "SIMILARITY_AVERAGE",
            "STATIC_WEIGHTS",
        }:
            raise ValueError("unsupported consensus mode")
        if len(self.variants) == 1 and self.consensus != "SINGLE":
            raise ValueError("a single-view condition must use SINGLE consensus")
        if len(self.variants) > 1 and self.consensus == "SINGLE":
            raise ValueError("multi-view conditions require a consensus mode")
        weights = dict(self.static_weights)
        if len(weights) != len(self.static_weights):
            raise ValueError("static weight variants must be unique")
        if self.consensus == "STATIC_WEIGHTS":
            if self.static_weights and set(weights) != set(self.variants):
                raise ValueError("static weights must cover every condition variant")
            if any(
                not math.isfinite(value) or value < 0.0 for value in weights.values()
            ):
                raise ValueError("static weights must be finite and non-negative")
            if self.static_weights and math.fsum(weights.values()) <= 0.0:
                raise ValueError("static weights must have a positive sum")
        elif self.static_weights:
            raise ValueError("static_weights require STATIC_WEIGHTS consensus")


@dataclass(frozen=True, slots=True)
class TimingSummary:
    mean_ms: float
    median_ms: float
    p95_ms: float | None
    p99_ms: float | None
    sample_count: int


@dataclass(frozen=True, slots=True)
class RQ1RunResult:
    metadata: dict[str, Any]
    summary_rows: tuple[dict[str, Any], ...]
    predictions: tuple[dict[str, Any], ...]
    agreement: dict[str, Any]
    centroid_correctness: dict[str, Any]
    scale_baseline: tuple[dict[str, Any], ...]


class RQ1BenchmarkRunner:
    """Evaluate immutable conditions using calibration-built class prototypes."""

    def __init__(
        self,
        embedding_model: BaseEmbeddingModel,
        *,
        model_name: str,
        device: str,
        representation_config: RQ1RepresentationConfig | None = None,
        decision_config: RQ1DecisionConfig | None = None,
    ) -> None:
        self.model = embedding_model
        self.model_name = model_name
        self.device = device
        self.representation_config = representation_config or RQ1RepresentationConfig()
        self.decision_config = decision_config or RQ1DecisionConfig()
        self.builder = RQ1RepresentationBuilder()

    def run(
        self,
        dataset: RQ1Dataset,
        conditions: tuple[RQ1Condition, ...],
        *,
        split: RQ1Split = RQ1Split.VALIDATION,
        seed: int | None = None,
        bootstrap_repetitions: int = 200,
        diagnostics: bool = False,
        scale_sizes: tuple[int, ...] = (),
        timestamp: str | None = None,
    ) -> RQ1RunResult:
        if split is RQ1Split.CALIBRATION:
            raise ValueError("evaluation split must be VALIDATION or TEST")
        if not conditions or len({item.name for item in conditions}) != len(conditions):
            raise ValueError("conditions must have unique names")
        effective_seed = dataset.seed if seed is None else seed
        variants = tuple(
            dict.fromkeys(variant for item in conditions for variant in item.variants)
        )
        calibration = dataset.calibration
        evaluation = dataset.for_split(split)
        known_labels = tuple(sorted({item.label for item in calibration}))
        if not known_labels:
            raise ValueError("calibration split must contain known classes")

        vector_cache, timings, vector_counts = self._embed_examples(
            calibration + evaluation, variants
        )
        centroids, centroid_check = self._centroids(
            calibration, variants, vector_cache, known_labels
        )
        resolved_weights = {
            condition.name: (
                dict(condition.static_weights)
                if condition.static_weights
                else self._calibrate_static_weights(
                    calibration,
                    condition.variants,
                    vector_cache,
                    centroids,
                    known_labels,
                )
            )
            for condition in conditions
            if condition.consensus == "STATIC_WEIGHTS"
        }
        summary_rows: list[dict[str, Any]] = []
        raw_predictions: list[dict[str, Any]] = []
        for condition in conditions:
            predicted, scoring_times = self._evaluate_condition(
                condition,
                evaluation,
                vector_cache,
                centroids,
                known_labels,
                resolved_weights.get(condition.name, {}),
            )
            for source_kind in RQ1SourceKind:
                source_predictions = tuple(
                    item for item in predicted if item.source_kind == source_kind.value
                )
                if not source_predictions:
                    continue
                automated = compute_quality_metrics(source_predictions)
                authoritative = compute_quality_metrics(
                    source_predictions, authoritative=True
                )
                condition_variants = set(condition.variants)
                source_ids = {
                    item.stream_id
                    for item in evaluation
                    if item.source_kind is source_kind
                }
                build_values = [
                    value
                    for (stream_id, variant), value in timings["construction"].items()
                    if stream_id in source_ids and variant in condition_variants
                ]
                embed_values = [
                    value
                    for (stream_id, variant), value in timings["embedding"].items()
                    if stream_id in source_ids and variant in condition_variants
                ]
                construction = summarize_timings(build_values)
                embedding = summarize_timings(embed_values)
                source_scoring = [scoring_times[stream_id] for stream_id in source_ids]
                scoring = summarize_timings(source_scoring)
                total_values = [
                    math.fsum(
                        timings[name][(stream_id, variant)]
                        for name in ("construction", "embedding")
                        for variant in condition.variants
                    )
                    + scoring_times[stream_id]
                    for stream_id in source_ids
                ]
                total = summarize_timings(total_values)
                computed_vectors = sum(
                    vector_counts[variant] for variant in condition.variants
                )
                stored_vectors = len(condition.variants)
                dimensions = {
                    variant.value: len(vector_cache[(evaluation[0].stream_id, variant)])
                    for variant in condition.variants
                }
                row = {
                    "condition": condition.name,
                    "variants": [item.value for item in condition.variants],
                    "consensus": condition.consensus,
                    "resolved_static_weights": {
                        variant.value: value
                        for variant, value in resolved_weights.get(
                            condition.name, {}
                        ).items()
                    },
                    "source_kind": source_kind.value,
                    **automated.as_dict(),
                    "authoritative_after_feedback": authoritative.as_dict(),
                    "bootstrap_95": bootstrap_intervals(
                        source_predictions,
                        seed=effective_seed,
                        repetitions=bootstrap_repetitions,
                    ),
                    "construction_timing": asdict(construction),
                    "embedding_timing": asdict(embedding),
                    "scoring_timing": asdict(scoring),
                    "end_to_end_timing": asdict(total),
                    "embedding_vectors_computed_per_stream": computed_vectors,
                    "stored_vectors_per_stream": stored_vectors,
                    "embedding_dimensions": dimensions,
                    "approx_bytes_per_stream": math.fsum(dimensions.values()) * 4,
                    "qdrant_vector_count_estimate": stored_vectors * len(source_ids),
                }
                summary_rows.append(row)
            for item in predicted:
                record = asdict(item)
                record["condition"] = condition.name
                if not diagnostics:
                    record["per_view_similarities"] = {}
                raw_predictions.append(record)

        agreement = {
            source_kind.value: self._agreement_matrix(
                tuple(item for item in evaluation if item.source_kind is source_kind),
                variants,
                vector_cache,
                centroids,
            )
            for source_kind in RQ1SourceKind
            if any(item.source_kind is source_kind for item in evaluation)
        }
        scale = self._scale_baseline(
            scale_sizes, evaluation, variants, vector_cache, centroids
        )
        metadata = {
            "timestamp": timestamp or datetime.now(UTC).isoformat(),
            "git_commit": _git_commit(),
            "dataset_id": dataset.dataset_id,
            "dataset_version": dataset.version,
            "dataset_sha256": dataset.sha256,
            "embedding_model": self.model_name,
            "device": self.device,
            "embedding_normalization": "model-defined; benchmark does not renormalize",
            "evaluation_split": split.value,
            "random_seed": effective_seed,
            "representation_config": _jsonable(asdict(self.representation_config)),
            "decision_config": asdict(self.decision_config),
            "conditions": [
                {
                    **_jsonable(asdict(item)),
                    "resolved_static_weights": {
                        variant.value: value
                        for variant, value in resolved_weights.get(
                            item.name, {}
                        ).items()
                    },
                }
                for item in conditions
            ],
            "duplicate_filtering": asdict(dataset.duplicate_stats),
            "calibration_count": len(calibration),
            "calibration_counts_by_source": {
                source_kind.value: sum(
                    item.source_kind is source_kind for item in calibration
                )
                for source_kind in RQ1SourceKind
            },
            "evaluation_count": len(evaluation),
        }
        return RQ1RunResult(
            metadata,
            tuple(summary_rows),
            tuple(raw_predictions),
            agreement,
            centroid_check,
            scale,
        )

    def _embed_examples(self, examples, variants):
        cache: dict[tuple[str, RQ1Variant], tuple[float, ...]] = {}
        timings = {"construction": {}, "embedding": {}}
        vector_counts: dict[RQ1Variant, int] = {}
        for example in examples:
            for variant in variants:
                started = time.perf_counter_ns()
                representation = self.builder.build(
                    example, variant, self.representation_config
                )
                timings["construction"][(example.stream_id, variant)] = _elapsed_ms(
                    started
                )
                started = time.perf_counter_ns()
                vectors = tuple(
                    tuple(float(value) for value in vector)
                    for vector in self.model.encode(list(representation.texts))
                )
                timings["embedding"][(example.stream_id, variant)] = _elapsed_ms(
                    started
                )
                if len(vectors) != len(representation.texts):
                    raise ValueError(
                        "embedding model returned an unexpected vector count"
                    )
                cache[(example.stream_id, variant)] = fuse_vectors(
                    vectors, representation
                )
                vector_counts[variant] = len(vectors)
        return cache, timings, vector_counts

    @staticmethod
    def _centroids(calibration, variants, cache, labels):
        centroids = {}
        drift = {}
        for variant in variants:
            drift[variant.value] = {}
            for label in labels:
                vectors = tuple(
                    cache[(item.stream_id, variant)]
                    for item in calibration
                    if item.label == label
                )
                if not vectors:
                    raise ValueError(f"calibration label '{label}' has no examples")
                fresh = StreamClassEngine.compute_centroid(vectors)
                incremental = vectors[0]
                for count, vector in enumerate(vectors[1:], start=1):
                    incremental = StreamClassEngine.update_centroid(
                        incremental, count, vector
                    )
                differences = tuple(abs(a - b) for a, b in zip(fresh, incremental))
                centroids[(variant, label)] = fresh
                drift[variant.value][label] = {
                    "member_count": len(vectors),
                    "max_absolute_error": max(differences, default=0.0),
                    "mean_absolute_error": math.fsum(differences) / len(differences),
                    "l2_error": math.sqrt(
                        math.fsum(value * value for value in differences)
                    ),
                }
        return centroids, drift

    def _evaluate_condition(
        self, condition, examples, cache, centroids, labels, weights
    ):
        predictions = []
        scoring_times = {}
        for example in examples:
            started = time.perf_counter_ns()
            per_view = {
                variant.value: {
                    label: StreamClassEngine.cosine_similarity(
                        cache[(example.stream_id, variant)], centroids[(variant, label)]
                    )
                    for label in labels
                }
                for variant in condition.variants
            }
            rankings = {
                view: tuple(sorted(scores, key=lambda label: (-scores[label], label)))
                for view, scores in per_view.items()
            }
            combined = self._combine(condition, per_view, rankings, weights, labels)
            ranked = tuple(sorted(labels, key=lambda label: (-combined[label], label)))
            top = ranked[0]
            runner = ranked[1] if len(ranked) > 1 else None
            top_similarity = combined[top]
            margin = top_similarity - (combined[runner] if runner else -1.0)
            if (
                top_similarity >= self.decision_config.known_min_similarity
                and margin >= self.decision_config.known_min_margin
            ):
                state, predicted, reason = "KNOWN", top, "known thresholds satisfied"
            elif top_similarity <= self.decision_config.unknown_max_similarity:
                state, predicted, reason = (
                    "UNKNOWN",
                    None,
                    "absolute similarity boundary",
                )
            else:
                state, predicted, reason = (
                    "UNCERTAIN",
                    None,
                    "between decision boundaries",
                )
            scoring_times[example.stream_id] = _elapsed_ms(started)
            top_votes = max(Counter(items[0] for items in rankings.values()).values())
            predictions.append(
                RQ1Prediction(
                    example.stream_id,
                    example.source_kind.value,
                    example.label,
                    example.label not in labels,
                    state,
                    predicted,
                    ranked,
                    reason,
                    top_similarity,
                    margin,
                    per_view,
                    {view: order[0] for view, order in rankings.items()},
                    top_votes,
                    example.decision_source,
                    example.authoritative_label,
                )
            )
        return tuple(predictions), scoring_times

    @staticmethod
    def _calibrate_static_weights(
        calibration, variants, cache, centroids, labels
    ) -> dict[RQ1Variant, float]:
        """Derive deterministic view weights from calibration-only LOO accuracy."""
        weights = {}
        for variant in variants:
            correct = 0
            for example in calibration:
                class_centroids = {}
                for label in labels:
                    other_vectors = tuple(
                        cache[(item.stream_id, variant)]
                        for item in calibration
                        if item.label == label and item.stream_id != example.stream_id
                    )
                    class_centroids[label] = (
                        StreamClassEngine.compute_centroid(other_vectors)
                        if other_vectors
                        else centroids[(variant, label)]
                    )
                predicted = min(
                    labels,
                    key=lambda label: (
                        -StreamClassEngine.cosine_similarity(
                            cache[(example.stream_id, variant)],
                            class_centroids[label],
                        ),
                        label,
                    ),
                )
                correct += predicted == example.label
            weights[variant] = correct / len(calibration)
        if math.fsum(weights.values()) == 0.0:
            return {variant: 1.0 for variant in variants}
        return weights

    @staticmethod
    def _combine(condition, per_view, rankings, weights, labels):
        if condition.consensus in {"SINGLE", "SIMILARITY_AVERAGE"}:
            return {
                label: math.fsum(scores[label] for scores in per_view.values())
                / len(per_view)
                for label in labels
            }
        if condition.consensus == "STATIC_WEIGHTS":
            total = math.fsum(weights.values())
            return {
                label: math.fsum(
                    weights[variant] * per_view[variant.value][label]
                    for variant in condition.variants
                )
                / total
                for label in labels
            }
        votes = Counter(order[0] for order in rankings.values())
        return {
            label: votes[label]
            + math.fsum(scores[label] for scores in per_view.values())
            / (len(per_view) * 4.0)
            for label in labels
        }

    @staticmethod
    def _agreement_matrix(examples, variants, cache, centroids):
        labels = tuple(
            sorted({label for variant, label in centroids if variant == variants[0]})
        )
        tops = {
            variant: tuple(
                min(
                    labels,
                    key=lambda label: (
                        -StreamClassEngine.cosine_similarity(
                            cache[(item.stream_id, variant)],
                            centroids[(variant, label)],
                        ),
                        label,
                    ),
                )
                for item in examples
            )
            for variant in variants
        }
        agreement = {
            left.value: {
                right.value: (
                    sum(a == b for a, b in zip(tops[left], tops[right])) / len(examples)
                    if examples
                    else 0.0
                )
                for right in variants
            }
            for left in variants
        }
        score_series = {
            variant: tuple(
                StreamClassEngine.cosine_similarity(
                    cache[(item.stream_id, variant)], centroids[(variant, label)]
                )
                for item in examples
                for label in labels
            )
            for variant in variants
        }
        correlation = {
            left.value: {
                right.value: _pearson(score_series[left], score_series[right])
                for right in variants
            }
            for left in variants
        }
        return {
            "top_candidate_agreement": agreement,
            "similarity_score_pearson_correlation": correlation,
        }

    @staticmethod
    def _scale_baseline(sizes, examples, variants, cache, centroids):
        if any(size <= 0 for size in sizes):
            raise ValueError("scale sizes must be positive")
        if not sizes or not examples:
            return ()
        variant = variants[0]
        labels = tuple(
            sorted(label for current, label in centroids if current == variant)
        )
        output = []
        stream_vectors = tuple(cache[(item.stream_id, variant)] for item in examples)
        for size in sizes:
            started = time.perf_counter_ns()
            for index in range(size):
                vector = cache[(examples[index % len(examples)].stream_id, variant)]
                for label in labels:
                    StreamClassEngine.cosine_similarity(
                        vector, centroids[(variant, label)]
                    )
            output.append(
                {
                    "stream_count": size,
                    "comparison_path": "class_centroids",
                    "class_count": len(labels),
                    "total_ms": _elapsed_ms(started),
                    "qdrant_ann": "not exercised by dependency-free smoke run",
                }
            )
            started = time.perf_counter_ns()
            for index in range(size):
                query = stream_vectors[index % len(stream_vectors)]
                for candidate_index in range(size):
                    candidate = stream_vectors[candidate_index % len(stream_vectors)]
                    StreamClassEngine.cosine_similarity(query, candidate)
            output.append(
                {
                    "stream_count": size,
                    "comparison_path": "brute_force_stream_vectors",
                    "candidate_vector_count": size,
                    "total_ms": _elapsed_ms(started),
                    "qdrant_ann": "not exercised by dependency-free smoke run",
                }
            )
        return tuple(output)


def write_rq1_artifacts(
    result: RQ1RunResult, output_dir: str | Path
) -> dict[str, Path]:
    """Persist raw JSON/JSONL and CSV summaries; docs can consume these outputs."""
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    json_path = target / "rq1_run.json"
    jsonl_path = target / "rq1_predictions.jsonl"
    csv_path = target / "rq1_ablation.csv"
    json_path.write_text(
        json.dumps(_jsonable(asdict(result)), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    jsonl_path.write_text(
        "".join(
            json.dumps(_jsonable(item), sort_keys=True) + "\n"
            for item in result.predictions
        ),
        encoding="utf-8",
    )
    columns = (
        "condition",
        "source_kind",
        "accuracy",
        "macro_f1",
        "known_class_false_positive_rate",
        "unknown_recall",
        "embedding_latency_mean_ms",
        "scoring_latency_mean_ms",
        "total_latency_mean_ms",
        "embedding_vectors_computed_per_stream",
        "stored_vectors_per_stream",
        "approx_bytes_per_stream",
    )
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(
            {
                **row,
                "embedding_latency_mean_ms": row["embedding_timing"]["mean_ms"],
                "scoring_latency_mean_ms": row["scoring_timing"]["mean_ms"],
                "total_latency_mean_ms": row["end_to_end_timing"]["mean_ms"],
            }
            for row in result.summary_rows
        )
    return {"json": json_path, "jsonl": jsonl_path, "csv": csv_path}


def summarize_timings(values: list[float]) -> TimingSummary:
    if not values:
        return TimingSummary(0.0, 0.0, None, None, 0)
    return TimingSummary(
        statistics.fmean(values),
        statistics.median(values),
        _percentile(values, 0.95) if len(values) >= 20 else None,
        _percentile(values, 0.99) if len(values) >= 100 else None,
        len(values),
    )


def _percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _elapsed_ms(started_ns: int) -> float:
    return (time.perf_counter_ns() - started_ns) / 1_000_000.0


def _pearson(left: tuple[float, ...], right: tuple[float, ...]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    left_mean, right_mean = statistics.fmean(left), statistics.fmean(right)
    left_delta = tuple(value - left_mean for value in left)
    right_delta = tuple(value - right_mean for value in right)
    denominator = math.sqrt(
        math.fsum(value * value for value in left_delta)
        * math.fsum(value * value for value in right_delta)
    )
    if denominator == 0.0:
        return None
    return math.fsum(a * b for a, b in zip(left_delta, right_delta)) / denominator


def _git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            check=True,
            text=True,
            timeout=5,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unavailable"


def _jsonable(value):
    if isinstance(value, dict):
        return {
            str(key.value if hasattr(key, "value") else key): _jsonable(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "value"):
        return value.value
    return value
