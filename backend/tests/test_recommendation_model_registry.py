from services.class_recommendation.learning import TrainingDataset, TrainingExample
from services.class_recommendation.model_registry import (
    ARTIFACT_FORMAT_VERSION,
    EvaluationGateConfig,
    approval_allowed,
    build_model_artifact,
    dataset_fingerprint,
    evaluate_offline_gate,
)


def _example(
    feedback_id: str,
    candidate_id: str,
    label: int,
    score: float,
    *,
    group: str,
):
    return TrainingExample(
        feedback_id=feedback_id,
        candidate_id=candidate_id,
        candidate_version=1,
        strategy_id="independent_hdbscan",
        objective="membership",
        target=f"topic/{feedback_id}",
        label=label,
        features=(score, 1.0),
        evaluation_group=group,
    )


def _dataset(examples):
    return TrainingDataset(
        objective="membership",
        feature_names=("key_score", "has_key"),
        examples=tuple(examples),
        skipped_by_reason={},
    )


def test_dataset_fingerprint_is_order_independent_for_same_semantic_examples():
    examples = [
        _example("a", "candidate-a", 1, 0.9, group="group-a"),
        _example("b", "candidate-b", 0, 0.2, group="group-b"),
    ]
    assert dataset_fingerprint(_dataset(examples)) == dataset_fingerprint(
        _dataset(reversed(examples))
    )


def test_model_artifact_serializes_scaler_and_logistic_state_without_pickle():
    dataset = _dataset(
        [
            _example("a", "candidate-a", 1, 0.9, group="group-a"),
            _example("b", "candidate-b", 0, 0.2, group="group-b"),
        ]
    )
    artifact = build_model_artifact(dataset)

    assert artifact["artifact_format_version"] == ARTIFACT_FORMAT_VERSION
    assert artifact["dataset_fingerprint"] == dataset_fingerprint(dataset)
    assert artifact["preprocessing"]["type"] == "standard_scaler"
    assert len(artifact["preprocessing"]["mean"]) == 2
    assert artifact["estimator"]["type"] == "logistic_regression"
    assert len(artifact["estimator"]["coefficients"]) == 2
    assert artifact["estimator"]["classes"] == [0, 1]


def _gate_ready_report(*, fixture_policy="excluded_by_default"):
    return {
        "status": "trained_offline",
        "sample_count": 40,
        "positive_count": 20,
        "negative_count": 20,
        "unique_evaluation_group_count": 8,
        "source_policy": {"fixture_feedback": fixture_policy},
        "cross_validation": {
            "status": "available",
            "balanced_accuracy": 0.72,
            "roc_auc": 0.76,
        },
    }


def test_offline_gate_passes_only_real_feedback_with_sufficient_grouped_metrics():
    gate = evaluate_offline_gate(_gate_ready_report())
    assert gate["passed"] is True
    assert all(check["passed"] for check in gate["checks"])


def test_offline_gate_rejects_fixture_feedback_even_when_metrics_are_high():
    gate = evaluate_offline_gate(
        _gate_ready_report(fixture_policy="included_by_explicit_request")
    )
    assert gate["passed"] is False
    fixture_check = next(
        check for check in gate["checks"] if check["name"] == "fixture_feedback_excluded"
    )
    assert fixture_check["passed"] is False


def test_gate_thresholds_are_explicit_policy():
    policy = EvaluationGateConfig(
        min_samples=50,
        min_positive=10,
        min_negative=10,
        min_evaluation_groups=10,
        min_balanced_accuracy=0.8,
        min_roc_auc=0.8,
    )
    gate = evaluate_offline_gate(_gate_ready_report(), policy)
    assert gate["passed"] is False
    assert gate["policy"]["min_samples"] == 50
    assert gate["policy"]["min_roc_auc"] == 0.8


def test_offline_approval_requires_matching_gate_passing_evaluation():
    model = {"model_id": "model-1", "status": "CANDIDATE"}
    evaluation = {
        "model_id": "model-1",
        "gate_report": {"passed": True},
    }
    assert approval_allowed(model, evaluation) == (True, None)

    wrong_model = {**evaluation, "model_id": "model-2"}
    allowed, reason = approval_allowed(model, wrong_model)
    assert allowed is False
    assert "does not belong" in reason

    failed_gate = {"model_id": "model-1", "gate_report": {"passed": False}}
    allowed, reason = approval_allowed(model, failed_gate)
    assert allowed is False
    assert "has not passed" in reason
