from services.class_recommendation.live_evaluation import evaluate_live_rows


def _row(
    feedback_id,
    action,
    *,
    candidate_id,
    score,
    baseline_rank,
    live_rank,
    model_id="quality-model",
    linked=True,
    fixture=False,
):
    member = "acceptance/run/topic" if fixture else f"real/{candidate_id}"
    return {
        "feedback_id": feedback_id,
        "candidate_id": candidate_id,
        "candidate_version": 1,
        "action_type": action,
        "topic": None,
        "evidence_snapshot": {
            "member_topics": [member],
            "candidate_evidence": {"member_topics": [member]},
        },
        "live_observation_id": f"obs-{feedback_id}" if linked else None,
        "strategy_id": "independent_hdbscan" if linked else None,
        "baseline_rank": baseline_rank if linked else None,
        "live_rank": live_rank if linked else None,
        "model_id": model_id if linked else None,
        "candidate_quality_score": score if linked else None,
        "model_version": 3 if linked else None,
    }


def test_live_evaluation_compares_live_and_baseline_pairwise_order():
    rows = [
        _row(
            "1",
            "ACCEPT_CANDIDATE",
            candidate_id="a",
            score=0.9,
            baseline_rank=3,
            live_rank=1,
        ),
        _row(
            "2",
            "DISMISS_CANDIDATE",
            candidate_id="b",
            score=0.1,
            baseline_rank=1,
            live_rank=3,
        ),
    ]

    report = evaluate_live_rows(rows)
    model = report["candidate_quality"]["models"][0]

    assert model["status"] == "evaluated"
    assert model["live_pairwise_accuracy"] == 1.0
    assert model["baseline_pairwise_accuracy"] == 0.0
    assert model["pairwise_accuracy_delta"] == 1.0
    assert model["balanced_accuracy"] == 1.0
    assert report["source"]["unshown_candidates_as_negative"] is False


def test_live_evaluation_latest_explicit_label_wins_per_candidate_version():
    rows = [
        _row(
            "1",
            "DISMISS_CANDIDATE",
            candidate_id="a",
            score=0.2,
            baseline_rank=1,
            live_rank=2,
        ),
        _row(
            "2",
            "ACCEPT_CANDIDATE",
            candidate_id="a",
            score=0.8,
            baseline_rank=1,
            live_rank=2,
        ),
    ]

    report = evaluate_live_rows(rows)
    model = report["candidate_quality"]["models"][0]

    assert report["candidate_quality"]["effective_sample_count"] == 1
    assert model["positive_count"] == 1
    assert model["negative_count"] == 0
    assert model["status"] == "not_evaluable"


def test_live_evaluation_excludes_fixture_and_unlinked_feedback_by_default():
    rows = [
        _row(
            "1",
            "ACCEPT_CANDIDATE",
            candidate_id="fixture",
            score=0.9,
            baseline_rank=1,
            live_rank=1,
            fixture=True,
        ),
        _row(
            "2",
            "ACCEPT_CANDIDATE",
            candidate_id="real",
            score=0.8,
            baseline_rank=1,
            live_rank=1,
            linked=False,
        ),
    ]

    report = evaluate_live_rows(rows)

    assert report["candidate_quality"]["effective_sample_count"] == 0
    assert report["skipped_by_reason"]["fixture_namespace_excluded"] == 1
    assert report["skipped_by_reason"]["no_live_observation"] == 1
    assert report["source"]["source_policy"]["fixture_feedback"] == "excluded_by_default"
