"""RQ1 evaluation for registry-defined pair evidence and shared stream context."""

from __future__ import annotations

import csv
import json
import math
import time
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path

from services.class_recommendation.domain import ClassPairPrototype, ClassProfile
from services.class_recommendation.embedding import PairEmbedder
from services.class_recommendation.evidence import PAIR_EVIDENCE_IDS
from services.class_recommendation.matching import PairClassMatcher, centroid
from services.class_recommendation.profiling import StreamProfiler
from services.class_recommendation.representations import PairRepresentationBuilder

from .rq1_dataset import RQ1Dataset, RQ1Split

CONDITIONS = (*PAIR_EVIDENCE_IDS, "stream_context", "equal_mean")


@dataclass(frozen=True, slots=True)
class RQ1RunResult:
    metadata: dict
    summary_rows: tuple[dict, ...]
    predictions: tuple[dict, ...]


class RQ1BenchmarkRunner:
    """Use production representations, prototypes, matching, and fusion."""

    def __init__(self, model, *, model_name: str, device: str) -> None:
        self.model = model
        self.model_name = model_name
        self.device = device
        self.profiler = StreamProfiler()
        self.builder = PairRepresentationBuilder()
        self.embedder = PairEmbedder(model)
        self.matcher = PairClassMatcher()
        self.embedding_calls = 0
        self.vector_count = 0

    def run(
        self,
        dataset: RQ1Dataset,
        *,
        split: RQ1Split = RQ1Split.VALIDATION,
    ) -> RQ1RunResult:
        if split is RQ1Split.CALIBRATION:
            raise ValueError("evaluation split must be VALIDATION or TEST")
        calibration = dataset.calibration
        evaluation = dataset.for_split(split)
        if not calibration or not evaluation:
            raise ValueError("calibration and evaluation examples are required")
        started = time.perf_counter()
        calibration_evidence = {
            item.stream_id: self._embed_example(item) for item in calibration
        }
        profiles = self._profiles(calibration, calibration_evidence)
        evaluation_evidence = {
            item.stream_id: self._embed_example(item) for item in evaluation
        }
        scored = []
        for item in evaluation:
            pairs, stream_context = evaluation_evidence[item.stream_id]
            recommendations = tuple(
                self.matcher.recommend(
                    canonical_topic=item.topic,
                    original_topic=item.topic,
                    topic_version=1,
                    pairs=pairs,
                    stream_context=stream_context,
                    profile=profile,
                    duplicate_pending=False,
                )
                for profile in profiles
            )
            scored.append((item, recommendations))
        predictions = []
        summary = []
        for condition in CONDITIONS:
            correct = 0
            top3 = 0
            reciprocal = []
            candidate_coverage = []
            prototype_coverage = []
            for item, recommendations in scored:
                ranked = sorted(
                    recommendations,
                    key=lambda row: (
                        -self._condition_score(row, condition),
                        row.class_id,
                    ),
                )
                labels = tuple(row.class_name for row in ranked)
                rank = labels.index(item.label) + 1 if item.label in labels else 0
                correct += rank == 1
                top3 += 0 < rank <= 3
                reciprocal.append(1.0 / rank if rank else 0.0)
                if ranked:
                    candidate_coverage.append(ranked[0].coverage.candidate_coverage)
                    prototype_coverage.append(ranked[0].coverage.prototype_coverage)
                predictions.append(
                    {
                        "condition": condition,
                        "stream_id": item.stream_id,
                        "source_kind": item.source_kind.value,
                        "expected_class": item.label,
                        "ranked_classes": labels,
                        "expected_rank": rank,
                        "top_score": (
                            self._condition_score(ranked[0], condition)
                            if ranked
                            else None
                        ),
                    }
                )
            count = len(evaluation)
            summary.append(
                {
                    "condition": condition,
                    "sample_count": count,
                    "top1_accuracy": correct / count,
                    "top3_accuracy": top3 / count,
                    "mean_reciprocal_rank": math.fsum(reciprocal) / count,
                    "candidate_coverage": self._mean(candidate_coverage),
                    "prototype_coverage": self._mean(prototype_coverage),
                    "pair_matching_accuracy": None,
                }
            )
        elapsed_ms = (time.perf_counter() - started) * 1000
        metadata = {
            "architecture": "pair-level-four-evidence-plus-shared-stream-context",
            "dataset_id": dataset.dataset_id,
            "dataset_version": dataset.version,
            "dataset_sha256": dataset.sha256,
            "evaluation_split": split.value,
            "embedding_model": self.model_name,
            "device": self.device,
            "embedding_normalization": "model-defined; benchmark does not renormalize",
            "conditions": list(CONDITIONS),
            "calibration_count": len(calibration),
            "evaluation_count": len(evaluation),
            "confirmed_aliases_excluded": (
                dataset.duplicate_stats.confirmed_aliases_excluded
            ),
            "keep_both_retained": dataset.duplicate_stats.keep_both_retained,
            "embedding_calls": self.embedding_calls,
            "vector_count": self.vector_count,
            "storage_estimate_bytes_float32": self.vector_count
            * self._vector_dimension(calibration_evidence)
            * 4,
            "elapsed_ms": elapsed_ms,
        }
        return RQ1RunResult(metadata, tuple(summary), tuple(predictions))

    def _embed_example(self, example):
        profile = self.profiler.profile(example.topic, example.tags, example.fields)
        representations = self.builder.build(
            profile,
            canonical_topic=example.topic,
            original_topic=example.topic,
            representation_version=1,
        )
        pairs = self.embedder.embed(representations)
        self.embedding_calls += int(bool(representations))
        self.vector_count += sum(len(record.vectors) for record in pairs)
        stream_text = self._stream_context_text(example.topic, example.tags)
        vector = tuple(float(value) for value in self.model.encode([stream_text])[0])
        self.embedding_calls += 1
        self.vector_count += 1
        return pairs, vector

    @staticmethod
    def _stream_context_text(topic, tags) -> str:
        tag_text = " ".join(f"{key} {value}" for key, value in tags.items())
        return f"{topic.replace('/', ' ')} {tag_text}"

    def _profiles(self, examples, evidence):
        profiles = []
        labels = sorted({item.label for item in examples})
        for class_index, label in enumerate(labels, 1):
            grouped = defaultdict(list)
            streams = []
            for item in examples:
                if item.label != label:
                    continue
                pairs, stream = evidence[item.stream_id]
                streams.append(stream)
                for pair in pairs:
                    grouped[pair.representation.identity].append(pair)
            prototypes = []
            for identity in sorted(grouped):
                records = grouped[identity]
                centroids = []
                for evidence_id in PAIR_EVIDENCE_IDS:
                    vectors = [
                        vector
                        for record in records
                        if (vector := record.vector_for(evidence_id)) is not None
                    ]
                    if vectors:
                        centroids.append((evidence_id, centroid(vectors)))
                prototypes.append(
                    ClassPairPrototype(
                        class_id=f"rq1-{class_index}",
                        class_name=label,
                        identity=identity,
                        centroids=tuple(centroids),
                        member_count=len(records),
                        prototype_version=1,
                    )
                )
            profiles.append(
                ClassProfile(
                    f"rq1-{class_index}",
                    label,
                    1,
                    tuple(prototypes),
                    centroid(streams),
                )
            )
        return tuple(profiles)

    @staticmethod
    def _condition_score(recommendation, condition):
        if condition == "equal_mean":
            return recommendation.overall_score
        value = recommendation.channel_scores.get(condition)
        return value if value is not None else -1.0

    @staticmethod
    def _mean(values):
        return math.fsum(values) / len(values) if values else 0.0

    @staticmethod
    def _vector_dimension(evidence):
        for pairs, stream in evidence.values():
            if pairs and pairs[0].vectors:
                return len(pairs[0].vectors[0][1])
            if stream:
                return len(stream)
        return 0


def write_rq1_artifacts(result: RQ1RunResult, output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "rq1_pair_recommendation.json"
    csv_path = output_dir / "rq1_pair_recommendation.csv"
    json_path.write_text(
        json.dumps(asdict(result), indent=2, sort_keys=True), encoding="utf-8"
    )
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=tuple(result.summary_rows[0]))
        writer.writeheader()
        writer.writerows(result.summary_rows)
    return {"json": json_path, "csv": csv_path}
