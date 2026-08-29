"""Build supervised datasets from immutable recommendation feedback snapshots.

This module is intentionally offline/evaluation-only. It never mutates embeddings,
centroids, Saved Classes, candidate membership, or the live recommendation ranking.
Human actions become labels over the exact evidence snapshot that produced them.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from statistics import mean
from typing import Literal

from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, balanced_accuracy_score, log_loss, roc_auc_score
from sklearn.model_selection import StratifiedGroupKFold, cross_val_predict
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from services.database.postgres import postgres_client


Objective = Literal["membership", "candidate_quality"]
EVIDENCE_IDS = ("key", "value", "key_value", "schema", "stream_context")
FEATURE_CONTRACT_VERSION = {
    "membership": "membership-evidence-v1",
    "candidate_quality": "candidate-quality-evidence-v1",
}

MEMBERSHIP_FEATURES = tuple(
    [f"{evidence_id}_score" for evidence_id in EVIDENCE_IDS]
    + [f"has_{evidence_id}" for evidence_id in EVIDENCE_IDS]
    + ["candidate_coverage", "prototype_coverage"]
)

CANDIDATE_QUALITY_FEATURES = tuple(
    [f"{evidence_id}_mean" for evidence_id in EVIDENCE_IDS]
    + [f"{evidence_id}_min" for evidence_id in EVIDENCE_IDS]
    + [f"{evidence_id}_availability" for evidence_id in EVIDENCE_IDS]
    + [
        "candidate_coverage_mean",
        "candidate_coverage_min",
        "prototype_coverage_mean",
        "prototype_coverage_min",
        "member_count",
        "discovery_evidence_count",
    ]
)


@dataclass(frozen=True, slots=True)
class TrainingExample:
    feedback_id: str
    candidate_id: str
    candidate_version: int
    strategy_id: str
    objective: Objective
    target: str
    label: int
    features: tuple[float, ...]
    evaluation_group: str | None = None


@dataclass(frozen=True, slots=True)
class TrainingDataset:
    objective: Objective
    feature_names: tuple[str, ...]
    examples: tuple[TrainingExample, ...]
    skipped_by_reason: dict[str, int]

    @property
    def labels(self) -> tuple[int, ...]:
        return tuple(example.label for example in self.examples)

    @property
    def groups(self) -> tuple[str, ...]:
        return tuple(
            example.evaluation_group or example.candidate_id
            for example in self.examples
        )

    @property
    def matrix(self) -> tuple[tuple[float, ...], ...]:
        return tuple(example.features for example in self.examples)


class RecommendationFeedbackDatasetBuilder:
    """Convert latest explicit feedback labels into deterministic feature datasets."""

    def __init__(self, database=postgres_client) -> None:
        self.database = database

    def build(self) -> dict[Objective, TrainingDataset]:
        rows = self.database.fetch_all(
            """
            SELECT feedback_id::text AS feedback_id,
                   candidate_id::text AS candidate_id,
                   candidate_version,
                   action_type,
                   topic,
                   evidence_snapshot,
                   occurred_at
            FROM recommended_class_feedback
            ORDER BY occurred_at, feedback_id
            """
        )

        # Multiple clicks on the same exact candidate version/target must not
        # overweight the dataset. The latest explicit label wins.
        latest_membership: dict[tuple[str, int, str], dict] = {}
        latest_quality: dict[tuple[str, int], dict] = {}
        for row in rows:
            action = row["action_type"]
            candidate_id = str(row["candidate_id"])
            version = int(row["candidate_version"])
            if action in {"KEEP_TOPIC", "REMOVE_TOPIC"}:
                topic = row.get("topic")
                if topic:
                    latest_membership[(candidate_id, version, topic)] = row
            elif action in {"ACCEPT_CANDIDATE", "DISMISS_CANDIDATE"}:
                latest_quality[(candidate_id, version)] = row

        membership_examples = []
        membership_skipped: Counter[str] = Counter()
        for key in sorted(latest_membership):
            row = latest_membership[key]
            example, reason = self._membership_example(row)
            if example is None:
                membership_skipped[reason or "unknown"] += 1
            else:
                membership_examples.append(example)

        quality_examples = []
        quality_skipped: Counter[str] = Counter()
        for key in sorted(latest_quality):
            row = latest_quality[key]
            example, reason = self._candidate_quality_example(row)
            if example is None:
                quality_skipped[reason or "unknown"] += 1
            else:
                quality_examples.append(example)

        return {
            "membership": TrainingDataset(
                objective="membership",
                feature_names=MEMBERSHIP_FEATURES,
                examples=tuple(membership_examples),
                skipped_by_reason=dict(membership_skipped),
            ),
            "candidate_quality": TrainingDataset(
                objective="candidate_quality",
                feature_names=CANDIDATE_QUALITY_FEATURES,
                examples=tuple(quality_examples),
                skipped_by_reason=dict(quality_skipped),
            ),
        }

    @classmethod
    def _membership_example(cls, row: dict):
        snapshot = row.get("evidence_snapshot") or {}
        candidate = snapshot.get("candidate_evidence") or {}
        topic = row.get("topic")
        topic_evidence = next(
            (
                item
                for item in candidate.get("topic_evidence", ())
                if item.get("topic") == topic
            ),
            None,
        )
        if topic_evidence is None:
            # The current discovery explanation uses an anchor reference and does
            # not emit a self-comparison row for that anchor. Keep the feedback in
            # the source table, but do not invent membership features for training.
            return None, "topic_evidence_missing"

        scores = cls._score_map(topic_evidence)
        values = [float(scores.get(evidence_id, 0.0)) for evidence_id in EVIDENCE_IDS]
        values.extend(
            1.0 if evidence_id in scores else 0.0 for evidence_id in EVIDENCE_IDS
        )
        coverage = topic_evidence.get("coverage") or {}
        values.extend(
            (
                float(coverage.get("candidate_coverage", 0.0)),
                float(coverage.get("prototype_coverage", 0.0)),
            )
        )
        members = candidate.get("member_topics") or snapshot.get("member_topics") or ()
        action = row["action_type"]
        return (
            TrainingExample(
                feedback_id=str(row["feedback_id"]),
                candidate_id=str(row["candidate_id"]),
                candidate_version=int(row["candidate_version"]),
                strategy_id=str(
                    snapshot.get("strategy_id")
                    or candidate.get("strategy_id")
                    or "unknown"
                ),
                objective="membership",
                target=str(topic),
                label=1 if action == "KEEP_TOPIC" else 0,
                features=tuple(values),
                evaluation_group=cls._member_group(members, str(row["candidate_id"])),
            ),
            None,
        )

    @classmethod
    def _candidate_quality_example(cls, row: dict):
        snapshot = row.get("evidence_snapshot") or {}
        candidate = snapshot.get("candidate_evidence") or {}
        topic_evidence = tuple(candidate.get("topic_evidence") or ())
        if not topic_evidence:
            return None, "candidate_evidence_missing"

        values: list[float] = []
        score_maps = [cls._score_map(item) for item in topic_evidence]
        for evidence_id in EVIDENCE_IDS:
            present = [
                scores[evidence_id]
                for scores in score_maps
                if evidence_id in scores
            ]
            values.append(float(mean(present)) if present else 0.0)
        for evidence_id in EVIDENCE_IDS:
            present = [
                scores[evidence_id]
                for scores in score_maps
                if evidence_id in scores
            ]
            values.append(float(min(present)) if present else 0.0)
        for evidence_id in EVIDENCE_IDS:
            present_count = sum(evidence_id in scores for scores in score_maps)
            values.append(present_count / len(score_maps))

        candidate_coverages = [
            float((item.get("coverage") or {}).get("candidate_coverage", 0.0))
            for item in topic_evidence
        ]
        prototype_coverages = [
            float((item.get("coverage") or {}).get("prototype_coverage", 0.0))
            for item in topic_evidence
        ]
        members = candidate.get("member_topics") or snapshot.get("member_topics") or ()
        discovery = (
            candidate.get("discovery_evidence")
            or snapshot.get("discovery_evidence")
            or ()
        )
        values.extend(
            (
                float(mean(candidate_coverages)),
                float(min(candidate_coverages)),
                float(mean(prototype_coverages)),
                float(min(prototype_coverages)),
                float(len(members)),
                float(len(discovery)),
            )
        )
        action = row["action_type"]
        return (
            TrainingExample(
                feedback_id=str(row["feedback_id"]),
                candidate_id=str(row["candidate_id"]),
                candidate_version=int(row["candidate_version"]),
                strategy_id=str(
                    snapshot.get("strategy_id")
                    or candidate.get("strategy_id")
                    or "unknown"
                ),
                objective="candidate_quality",
                target=str(row["candidate_id"]),
                label=1 if action == "ACCEPT_CANDIDATE" else 0,
                features=tuple(values),
                evaluation_group=cls._member_group(members, str(row["candidate_id"])),
            ),
            None,
        )

    @staticmethod
    def _score_map(topic_evidence: dict) -> dict[str, float]:
        items = (topic_evidence.get("channel_scores") or {}).get("items") or ()
        result = {}
        for item in items:
            evidence_id = item.get("evidence_id")
            score = item.get("score")
            if evidence_id in EVIDENCE_IDS and score is not None:
                result[str(evidence_id)] = float(score)
        return result

    @staticmethod
    def _member_group(members, fallback: str) -> str:
        canonical_members = sorted(str(member) for member in members)
        if not canonical_members:
            return fallback
        payload = json.dumps(
            canonical_members, ensure_ascii=False, separators=(",", ":")
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _model() -> Pipeline:
    return Pipeline(
        steps=(
            ("scale", StandardScaler()),
            (
                "logistic_regression",
                LogisticRegression(max_iter=2000, solver="liblinear", random_state=42),
            ),
        )
    )


def train_offline_report(dataset: TrainingDataset) -> dict:
    """Fit an interpretable baseline and return diagnostics without promoting it."""
    label_counts = Counter(dataset.labels)
    strategy_counts = Counter(example.strategy_id for example in dataset.examples)
    base = {
        "objective": dataset.objective,
        "feature_contract_version": FEATURE_CONTRACT_VERSION[dataset.objective],
        "feature_contract": list(dataset.feature_names),
        "sample_count": len(dataset.examples),
        "positive_count": label_counts.get(1, 0),
        "negative_count": label_counts.get(0, 0),
        "unique_candidate_count": len(
            {example.candidate_id for example in dataset.examples}
        ),
        "unique_evaluation_group_count": len(set(dataset.groups)),
        "strategy_counts": dict(sorted(strategy_counts.items())),
        "skipped_by_reason": dataset.skipped_by_reason,
        "promotion": "none",
    }
    if len(label_counts) < 2:
        return {
            **base,
            "status": "not_trainable",
            "reason": "both positive and negative labels are required",
            "standardized_coefficients": {},
            "cross_validation": {"status": "not_available"},
        }

    model = _model()
    model.fit(dataset.matrix, dataset.labels)
    estimator: LogisticRegression = model.named_steps["logistic_regression"]
    coefficients = {
        feature: float(value)
        for feature, value in zip(
            dataset.feature_names, estimator.coef_[0], strict=True
        )
    }
    ordered_coefficients = dict(
        sorted(coefficients.items(), key=lambda item: (-abs(item[1]), item[0]))
    )

    groups_by_label = {
        label: {
            group
            for group, y in zip(dataset.groups, dataset.labels, strict=True)
            if y == label
        }
        for label in (0, 1)
    }
    split_count = min(
        5,
        len(set(dataset.groups)),
        len(groups_by_label[0]),
        len(groups_by_label[1]),
    )
    cv_report: dict
    if split_count < 2:
        cv_report = {
            "status": "not_available",
            "reason": "each label must occur across at least two member-set groups",
        }
    else:
        cv = StratifiedGroupKFold(
            n_splits=split_count, shuffle=True, random_state=42
        )
        try:
            probabilities = cross_val_predict(
                _model(),
                dataset.matrix,
                dataset.labels,
                groups=dataset.groups,
                cv=cv,
                method="predict_proba",
            )[:, 1]
            predictions = [1 if value >= 0.5 else 0 for value in probabilities]
            cv_report = {
                "status": "available",
                "folds": split_count,
                "accuracy": float(accuracy_score(dataset.labels, predictions)),
                "balanced_accuracy": float(
                    balanced_accuracy_score(dataset.labels, predictions)
                ),
                "roc_auc": float(roc_auc_score(dataset.labels, probabilities)),
                "log_loss": float(
                    log_loss(dataset.labels, probabilities, labels=[0, 1])
                ),
            }
        except ValueError as exc:
            cv_report = {
                "status": "not_available",
                "reason": f"grouped cross-validation could not be formed: {exc}",
            }

    return {
        **base,
        "status": "trained_offline",
        "model": "standard_scaler+logistic_regression",
        "intercept": float(estimator.intercept_[0]),
        "standardized_coefficients": ordered_coefficients,
        "cross_validation": cv_report,
    }


def build_learning_report(database=postgres_client) -> dict:
    datasets = RecommendationFeedbackDatasetBuilder(database).build()
    return {
        objective: train_offline_report(dataset)
        for objective, dataset in datasets.items()
    }
