from services.class_recommendation.shadow_evaluation import evaluate_shadow_rows


def _row(
    feedback_id,
    action,
    *,
    candidate_id,
    topic=None,
    membership_score=None,
    quality_score=None,
    baseline_rank=1,
    linked=True,
    shadow_run_id="shadow-run-1",
):
    membership_scores = {}
    if topic is not None and membership_score is not None:
        membership_scores[topic] = {"score": membership_score, "reason": None}
    return {
        "feedback_id": feedback_id,
        "candidate_id": candidate_id,
        "candidate_version": 1,
        "action_type": action,
        "topic": topic,
        "evidence_snapshot": {},
        "shadow_observation_id": f"obs-{feedback_id}" if linked else None,
        "shadow_run_id": shadow_run_id if linked else None,
        "strategy_id": "independent_hdbscan" if linked else None,
        "baseline_rank": baseline_rank if linked else None,
        "membership_model_id": "membership-model" if linked else None,
        "candidate_quality_model_id": "quality-model" if linked else None,
        "membership_scores": membership_scores if linked else None,
        "candidate_quality_score": quality_score if linked else None,
        "membership_model_version": 3 if linked else None,
        "candidate_quality_model_version": 4 if linked else None,
    }


def test_shadow_evaluation_uses_latest_explicit_membership_label_per_target():
    rows = [
        _row(
            "1",
            "KEEP_TOPIC",
            candidate_id="candidate-a",
            topic="topic/b",
            membership_score=0.9,
        ),
        _row(
            "2",
            "REMOVE_TOPIC",
            candidate_id="candidate-a",
            topic="topic/b",
            membership_score=0.2,
        ),
        _row(
            "3",
            "KEEP_TOPIC",
            candidate_id="candidate-b",
            topic="topic/d",
            membership_score=0.8,
        ),
        _row(
            "4",
            "KEEP_TOPIC",
            candidate_id="unlinked",
            topic="topic/x",
            membership_score=0.99,
            linked=False,
        ),
    ]

    report = evaluate_shadow_rows(rows)

    assert report["source"]["total_feedback_events"] == 4
    assert report["source"]["eligible_feedback_events"] == 4
    assert report["source"]["linked_shadow_events"] == 3
    assert report["source"]["unshown_candidates_as_negative"] is False
    assert report["membership"]["effective_sample_count"] == 2
    model = report["membership"]["models"][0]
    assert model["model_id"] == "membership-model"
    assert model["model_version"] == 3
    assert model["positive_count"] == 1
    assert model["negative_count"] == 1
    assert model["status"] == "evaluated"
    assert model["accuracy"] == 1.0
    assert model["balanced_accuracy"] == 1.0
    assert model["roc_auc"] == 1.0
    assert report["skipped_by_reason"]["no_shadow_observation"] == 1


def test_candidate_quality_report_compares_baseline_and_learned_within_run():
    rows = [
        _row(
            "1",
            "ACCEPT_CANDIDATE",
            candidate_id="candidate-a",
            quality_score=0.9,
            baseline_rank=4,
        ),
        _row(
            "2",
            "DISMISS_CANDIDATE",
            candidate_id="candidate-b",
            quality_score=0.1,
            baseline_rank=1,
        ),
    ]

    report = evaluate_shadow_rows(rows)
    model = report["candidate_quality"]["models"][0]

    assert model["status"] == "evaluated"
    assert model["sample_count"] == 2
    assert model["accuracy"] == 1.0
    assert model["pairwise_grouping"] == "same_shadow_run_only"
    assert model["pairwise_comparison_count"] == 1
    assert model["learned_pairwise_accuracy"] == 1.0
    assert model["baseline_pairwise_accuracy"] == 0.0
    assert model["pairwise_accuracy_delta"] == 1.0
    assert report["ranking_effect"] == "none"


def test_shadow_evaluation_does_not_compare_ranks_across_runs():
    rows = [
        _row(
            "1",
            "ACCEPT_CANDIDATE",
            candidate_id="candidate-a",
            quality_score=0.9,
            baseline_rank=2,
            shadow_run_id="run-a",
        ),
        _row(
            "2",
            "DISMISS_CANDIDATE",
            candidate_id="candidate-b",
            quality_score=0.1,
            baseline_rank=1,
            shadow_run_id="run-b",
        ),
    ]

    report = evaluate_shadow_rows(rows)
    model = report["candidate_quality"]["models"][0]

    assert model["pairwise_comparison_count"] == 0
    assert model["pairwise_accuracy_delta"] is None


def test_shadow_evaluation_does_not_invent_anchor_membership_scores():
    rows = [
        {
            **_row(
                "1",
                "KEEP_TOPIC",
                candidate_id="candidate-a",
                topic="anchor",
                membership_score=None,
            ),
            "membership_scores": {
                "anchor": {"score": None, "reason": "topic_evidence_missing"}
            },
        }
    ]

    report = evaluate_shadow_rows(rows)

    assert report["membership"]["effective_sample_count"] == 0
    assert report["skipped_by_reason"]["membership_score_missing"] == 1


def test_shadow_evaluation_excludes_acceptance_fixture_feedback_by_default():
    fixture = _row(
        "fixture",
        "ACCEPT_CANDIDATE",
        candidate_id="fixture-candidate",
        quality_score=0.99,
    )
    fixture["evidence_snapshot"] = {
        "candidate_evidence": {
            "member_topics": [
                "acceptance/shadow-run/temperature/a",
                "acceptance/shadow-run/temperature/b",
            ]
        }
    }
    real = _row(
        "real",
        "DISMISS_CANDIDATE",
        candidate_id="real-candidate",
        quality_score=0.1,
    )

    report = evaluate_shadow_rows([fixture, real])
    smoke = evaluate_shadow_rows(
        [fixture, real],
        include_fixture_feedback=True,
    )

    assert report["source"]["total_feedback_events"] == 2
    assert report["source"]["eligible_feedback_events"] == 1
    assert report["source"]["source_policy"]["fixture_feedback"] == "excluded_by_default"
    assert report["skipped_by_reason"]["fixture_namespace_excluded"] == 1
    assert report["candidate_quality"]["effective_sample_count"] == 1
    assert smoke["source"]["eligible_feedback_events"] == 2
    assert smoke["source"]["source_policy"]["fixture_feedback"] == "included_by_explicit_request"
