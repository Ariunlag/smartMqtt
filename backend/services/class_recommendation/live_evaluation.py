"""Evaluate live candidate ordering against explicit feedback and its baseline counterfactual."""

from __future__ import annotations

from collections import Counter, defaultdict
from statistics import mean

from sklearn.metrics import accuracy_score, balanced_accuracy_score, log_loss, roc_auc_score

from services.database.postgres import postgres_client

from .learning import DEFAULT_EXCLUDED_TOPIC_PREFIXES
from .shadow_evaluation import QUALITY_ACTIONS, _is_fixture_feedback, _pairwise_order_accuracy


def evaluate_live_rows(
    rows: list[dict],
    *,
    include_fixture_feedback: bool = False,
    excluded_topic_prefixes: tuple[str, ...] = DEFAULT_EXCLUDED_TOPIC_PREFIXES,
) -> dict:
    skipped = Counter()
    eligible = []
    for row in rows:
        if not include_fixture_feedback and _is_fixture_feedback(row, excluded_topic_prefixes):
            skipped["fixture_namespace_excluded"] += 1
            continue
        eligible.append(row)

    latest: dict[tuple[str, str, int], dict] = {}
    for row in eligible:
        if not row.get("live_observation_id"):
            skipped["no_live_observation"] += 1
            continue
        action = row.get("action_type")
        if action not in QUALITY_ACTIONS:
            skipped["not_candidate_quality_action"] += 1
            continue
        if row.get("candidate_quality_score") is None:
            skipped["candidate_quality_score_missing"] += 1
            continue
        model_id = str(row.get("model_id") or "")
        if not model_id:
            skipped["live_model_missing"] += 1
            continue
        candidate_id = str(row["candidate_id"])
        version = int(row["candidate_version"])
        key = (model_id, candidate_id, version)
        latest[key] = {
            "model_id": model_id,
            "model_version": int(row.get("model_version") or 0),
            "candidate_id": candidate_id,
            "candidate_version": version,
            "strategy_id": str(row.get("strategy_id") or "unknown"),
            "label": QUALITY_ACTIONS[action],
            "score": float(row["candidate_quality_score"]),
            "baseline_rank": int(row["baseline_rank"]),
            "live_rank": int(row["live_rank"]),
        }

    by_model = defaultdict(list)
    for item in latest.values():
        by_model[(item["model_id"], item["model_version"])].append(item)

    reports = []
    for (model_id, model_version), examples in sorted(by_model.items()):
        labels = [item["label"] for item in examples]
        scores = [item["score"] for item in examples]
        counts = Counter(labels)
        live_pairwise, pair_count = _pairwise_order_accuracy(
            examples, value_key="live_rank", positive_higher=False
        )
        baseline_pairwise, _ = _pairwise_order_accuracy(
            examples, value_key="baseline_rank", positive_higher=False
        )
        report = {
            "model_id": model_id,
            "model_version": model_version,
            "sample_count": len(examples),
            "positive_count": counts.get(1, 0),
            "negative_count": counts.get(0, 0),
            "unique_candidate_count": len(
                {(item["candidate_id"], item["candidate_version"]) for item in examples}
            ),
            "strategy_counts": dict(
                sorted(Counter(item["strategy_id"] for item in examples).items())
            ),
            "positive_mean_live_rank": (
                float(mean(item["live_rank"] for item in examples if item["label"] == 1))
                if counts.get(1, 0)
                else None
            ),
            "negative_mean_live_rank": (
                float(mean(item["live_rank"] for item in examples if item["label"] == 0))
                if counts.get(0, 0)
                else None
            ),
            "pairwise_comparison_count": pair_count,
            "live_pairwise_accuracy": live_pairwise,
            "baseline_pairwise_accuracy": baseline_pairwise,
            "pairwise_accuracy_delta": (
                float(live_pairwise - baseline_pairwise)
                if live_pairwise is not None and baseline_pairwise is not None
                else None
            ),
        }
        if len(counts) < 2:
            report.update(
                {
                    "status": "not_evaluable",
                    "reason": "both positive and negative explicit labels are required",
                }
            )
        else:
            predictions = [1 if score >= 0.5 else 0 for score in scores]
            report.update(
                {
                    "status": "evaluated",
                    "accuracy": float(accuracy_score(labels, predictions)),
                    "balanced_accuracy": float(balanced_accuracy_score(labels, predictions)),
                    "roc_auc": float(roc_auc_score(labels, scores)),
                    "log_loss": float(log_loss(labels, scores, labels=[0, 1])),
                }
            )
        reports.append(report)

    linked_count = sum(bool(row.get("live_observation_id")) for row in eligible)
    return {
        "source": {
            "total_feedback_events": len(rows),
            "eligible_feedback_events": len(eligible),
            "linked_live_events": linked_count,
            "unlinked_feedback_events": len(eligible) - linked_count,
            "label_policy": "explicit_candidate_feedback_only",
            "unshown_candidates_as_negative": False,
            "repeat_policy": "latest_label_per_model_candidate_version",
            "source_policy": {
                "fixture_feedback": (
                    "included_by_explicit_request"
                    if include_fixture_feedback
                    else "excluded_by_default"
                ),
                "excluded_topic_prefixes": list(excluded_topic_prefixes),
            },
        },
        "skipped_by_reason": dict(sorted(skipped.items())),
        "candidate_quality": {
            "models": reports,
            "effective_sample_count": len(latest),
        },
    }


def build_live_evaluation_report(
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
               f.live_observation_id::text AS live_observation_id,
               f.occurred_at,
               o.strategy_id,
               o.baseline_rank,
               o.live_rank,
               o.model_id::text AS model_id,
               o.candidate_quality_score,
               m.model_version
        FROM recommended_class_feedback f
        LEFT JOIN recommendation_live_observations o
          ON o.observation_id = f.live_observation_id
        LEFT JOIN recommendation_model_versions m
          ON m.model_id = o.model_id
        ORDER BY f.occurred_at, f.feedback_id
        """
    )
    return evaluate_live_rows(
        list(rows),
        include_fixture_feedback=include_fixture_feedback,
    )
