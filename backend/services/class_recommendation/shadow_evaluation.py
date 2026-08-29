"""Evaluate persisted shadow scores against explicit user feedback only.

Unshown candidates are never treated as negatives. Repeated feedback is deduplicated
within each exact model/candidate-version/target so the latest explicit label wins,
matching the offline training contract. Synthetic acceptance namespaces are excluded by
default and can only be included by an explicit smoke-test request.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from statistics import mean

from sklearn.metrics import accuracy_score, balanced_accuracy_score, log_loss, roc_auc_score

from services.database.postgres import postgres_client

from .learning import DEFAULT_EXCLUDED_TOPIC_PREFIXES

MEMBERSHIP_ACTIONS = {"KEEP_TOPIC": 1, "REMOVE_TOPIC": 0}
QUALITY_ACTIONS = {"ACCEPT_CANDIDATE": 1, "DISMISS_CANDIDATE": 0}


def _score_from_membership(payload: dict | None, topic: str | None) -> float | None:
    if not payload or not topic:
        return None
    item = payload.get(topic)
    if not isinstance(item, dict):
        return None
    value = item.get("score")
    return float(value) if value is not None else None


def _is_fixture_feedback(row: dict, excluded_prefixes: tuple[str, ...]) -> bool:
    snapshot = row.get("evidence_snapshot") or {}
    candidate = snapshot.get("candidate_evidence") or {}
    members = candidate.get("member_topics") or snapshot.get("member_topics") or ()
    topics = [str(member) for member in members]
    if row.get("topic"):
        topics.append(str(row["topic"]))
    return any(
        topic.startswith(prefix)
        for topic in topics
        for prefix in excluded_prefixes
    )


def _pairwise_order_accuracy(
    examples: list[dict],
    *,
    value_key: str,
    positive_higher: bool,
    group_key: str | None = None,
) -> tuple[float | None, int]:
    positives = [item for item in examples if int(item["label"]) == 1]
    negatives = [item for item in examples if int(item["label"]) == 0]
    comparisons = 0
    correct = 0.0
    for positive in positives:
        for negative in negatives:
            if group_key is not None:
                positive_group = positive.get(group_key)
                negative_group = negative.get(group_key)
                if not positive_group or positive_group != negative_group:
                    continue
            left = float(positive[value_key])
            right = float(negative[value_key])
            comparisons += 1
            if left == right:
                correct += 0.5
            elif (left > right) == positive_higher:
                correct += 1.0
    if comparisons == 0:
        return None, 0
    return float(correct / comparisons), comparisons


def _metric_report(examples: list[dict], *, include_baseline_rank: bool) -> dict:
    labels = [int(item["label"]) for item in examples]
    scores = [float(item["score"]) for item in examples]
    counts = Counter(labels)
    base = {
        "sample_count": len(examples),
        "positive_count": counts.get(1, 0),
        "negative_count": counts.get(0, 0),
        "unique_candidate_count": len(
            {(item["candidate_id"], item["candidate_version"]) for item in examples}
        ),
        "positive_mean_score": (
            float(mean(item["score"] for item in examples if item["label"] == 1))
            if counts.get(1, 0)
            else None
        ),
        "negative_mean_score": (
            float(mean(item["score"] for item in examples if item["label"] == 0))
            if counts.get(0, 0)
            else None
        ),
    }
    if include_baseline_rank:
        base["positive_mean_baseline_rank"] = (
            float(mean(item["baseline_rank"] for item in examples if item["label"] == 1))
            if counts.get(1, 0)
            else None
        )
        base["negative_mean_baseline_rank"] = (
            float(mean(item["baseline_rank"] for item in examples if item["label"] == 0))
            if counts.get(0, 0)
            else None
        )
        learned_pairwise, pair_count = _pairwise_order_accuracy(
            examples,
            value_key="score",
            positive_higher=True,
            group_key="shadow_run_id",
        )
        baseline_pairwise, _ = _pairwise_order_accuracy(
            examples,
            value_key="baseline_rank",
            positive_higher=False,
            group_key="shadow_run_id",
        )
        base.update(
            {
                "pairwise_grouping": "same_shadow_run_only",
                "pairwise_comparison_count": pair_count,
                "learned_pairwise_accuracy": learned_pairwise,
                "baseline_pairwise_accuracy": baseline_pairwise,
                "pairwise_accuracy_delta": (
                    float(learned_pairwise - baseline_pairwise)
                    if learned_pairwise is not None and baseline_pairwise is not None
                    else None
                ),
            }
        )

    if len(counts) < 2:
        return {
            **base,
            "status": "not_evaluable",
            "reason": "both positive and negative explicit labels are required",
        }

    predictions = [1 if score >= 0.5 else 0 for score in scores]
    return {
        **base,
        "status": "evaluated",
        "accuracy": float(accuracy_score(labels, predictions)),
        "balanced_accuracy": float(balanced_accuracy_score(labels, predictions)),
        "roc_auc": float(roc_auc_score(labels, scores)),
        "log_loss": float(log_loss(labels, scores, labels=[0, 1])),
    }


def evaluate_shadow_rows(
    rows: list[dict],
    *,
    include_fixture_feedback: bool = False,
    excluded_topic_prefixes: tuple[str, ...] = DEFAULT_EXCLUDED_TOPIC_PREFIXES,
) -> dict:
    """Build deterministic per-model shadow metrics from joined feedback rows."""
    skipped = Counter()
    eligible_rows = []
    for row in rows:
        if not include_fixture_feedback and _is_fixture_feedback(
            row, excluded_topic_prefixes
        ):
            skipped["fixture_namespace_excluded"] += 1
            continue
        eligible_rows.append(row)

    linked_count = sum(
        bool(row.get("shadow_observation_id")) for row in eligible_rows
    )
    source = {
        "total_feedback_events": len(rows),
        "eligible_feedback_events": len(eligible_rows),
        "linked_shadow_events": linked_count,
        "unlinked_feedback_events": len(eligible_rows) - linked_count,
        "label_policy": "explicit_feedback_only",
        "unshown_candidates_as_negative": False,
        "repeat_policy": "latest_label_per_model_candidate_version_target",
        "source_policy": {
            "fixture_feedback": (
                "included_by_explicit_request"
                if include_fixture_feedback
                else "excluded_by_default"
            ),
            "excluded_topic_prefixes": list(excluded_topic_prefixes),
        },
    }

    membership_latest: dict[tuple, dict] = {}
    quality_latest: dict[tuple, dict] = {}

    for row in eligible_rows:
        if not row.get("shadow_observation_id"):
            skipped["no_shadow_observation"] += 1
            continue
        action = row.get("action_type")
        candidate_id = str(row.get("candidate_id"))
        version = int(row.get("candidate_version") or 0)

        if action in MEMBERSHIP_ACTIONS:
            model_id = row.get("membership_model_id")
            topic = row.get("topic")
            if not model_id:
                skipped["membership_model_missing"] += 1
                continue
            score = _score_from_membership(row.get("membership_scores"), topic)
            if score is None:
                skipped["membership_score_missing"] += 1
                continue
            key = (str(model_id), candidate_id, version, str(topic))
            membership_latest[key] = {
                "feedback_id": str(row["feedback_id"]),
                "model_id": str(model_id),
                "model_version": int(row.get("membership_model_version") or 0),
                "candidate_id": candidate_id,
                "candidate_version": version,
                "strategy_id": str(row.get("strategy_id") or "unknown"),
                "target": str(topic),
                "label": MEMBERSHIP_ACTIONS[action],
                "score": score,
                "baseline_rank": int(row.get("baseline_rank") or 0),
                "shadow_run_id": str(row.get("shadow_run_id") or ""),
            }
        elif action in QUALITY_ACTIONS:
            model_id = row.get("candidate_quality_model_id")
            score = row.get("candidate_quality_score")
            if not model_id:
                skipped["candidate_quality_model_missing"] += 1
                continue
            if score is None:
                skipped["candidate_quality_score_missing"] += 1
                continue
            key = (str(model_id), candidate_id, version)
            quality_latest[key] = {
                "feedback_id": str(row["feedback_id"]),
                "model_id": str(model_id),
                "model_version": int(row.get("candidate_quality_model_version") or 0),
                "candidate_id": candidate_id,
                "candidate_version": version,
                "strategy_id": str(row.get("strategy_id") or "unknown"),
                "target": candidate_id,
                "label": QUALITY_ACTIONS[action],
                "score": float(score),
                "baseline_rank": int(row.get("baseline_rank") or 0),
                "shadow_run_id": str(row.get("shadow_run_id") or ""),
            }
        else:
            skipped["unknown_action"] += 1

    membership_by_model = defaultdict(list)
    for item in membership_latest.values():
        membership_by_model[(item["model_id"], item["model_version"])].append(item)

    quality_by_model = defaultdict(list)
    for item in quality_latest.values():
        quality_by_model[(item["model_id"], item["model_version"])].append(item)

    def build_models(groups, *, include_baseline_rank: bool):
        reports = []
        for (model_id, model_version), examples in sorted(groups.items()):
            examples.sort(
                key=lambda item: (
                    item["candidate_id"],
                    item["candidate_version"],
                    item["target"],
                )
            )
            strategies = Counter(item["strategy_id"] for item in examples)
            reports.append(
                {
                    "model_id": model_id,
                    "model_version": model_version,
                    "strategy_counts": dict(sorted(strategies.items())),
                    **_metric_report(
                        examples,
                        include_baseline_rank=include_baseline_rank,
                    ),
                }
            )
        return reports

    return {
        "source": source,
        "skipped_by_reason": dict(sorted(skipped.items())),
        "membership": {
            "models": build_models(membership_by_model, include_baseline_rank=False),
            "effective_sample_count": len(membership_latest),
        },
        "candidate_quality": {
            "models": build_models(quality_by_model, include_baseline_rank=True),
            "effective_sample_count": len(quality_latest),
        },
        "ranking_effect": "none",
    }


def build_shadow_evaluation_report(
    database=postgres_client,
    *,
    include_fixture_feedback: bool = False,
) -> dict:
    rows = database.fetch_all(
        """
        SELECT f.feedback_id::text AS feedback_id,
               f.candidate_id::text AS candidate_id,
               f.candidate_version,
               f.action_type,
               f.topic,
               f.evidence_snapshot,
               f.shadow_observation_id::text AS shadow_observation_id,
               f.occurred_at,
               o.shadow_run_id::text AS shadow_run_id,
               o.strategy_id,
               o.baseline_rank,
               o.membership_model_id::text AS membership_model_id,
               o.candidate_quality_model_id::text AS candidate_quality_model_id,
               o.membership_scores,
               o.candidate_quality_score,
               mm.model_version AS membership_model_version,
               qm.model_version AS candidate_quality_model_version
        FROM recommended_class_feedback f
        LEFT JOIN recommendation_shadow_observations o
          ON o.observation_id = f.shadow_observation_id
        LEFT JOIN recommendation_model_versions mm
          ON mm.model_id = o.membership_model_id
        LEFT JOIN recommendation_model_versions qm
          ON qm.model_id = o.candidate_quality_model_id
        ORDER BY f.occurred_at, f.feedback_id
        """
    )
    return evaluate_shadow_rows(
        list(rows),
        include_fixture_feedback=include_fixture_feedback,
    )
