import pytest

from services.class_recommendation.live_deployment import (
    LivePromotionGateConfig,
    build_live_promotion_report,
)


MODEL_ID = "00000000-0000-0000-0000-000000000777"


class FakeDatabase:
    def __init__(self, objective="candidate_quality", status="OFFLINE_APPROVED"):
        self.model = {
            "model_id": MODEL_ID,
            "objective": objective,
            "model_version": 4,
            "feature_contract_version": "candidate-quality-evidence-v1",
            "status": status,
        }

    def fetch_one(self, sql, params=()):
        if "FROM recommendation_model_versions" in " ".join(sql.split()):
            return self.model
        raise AssertionError(sql)


def _shadow_report(*, delta=0.1, balanced_accuracy=0.72, roc_auc=0.75):
    return {
        "source": {
            "source_policy": {
                "fixture_feedback": "excluded_by_default",
                "excluded_topic_prefixes": ["acceptance/"],
            }
        },
        "candidate_quality": {
            "models": [
                {
                    "model_id": MODEL_ID,
                    "model_version": 4,
                    "status": "evaluated",
                    "sample_count": 24,
                    "positive_count": 12,
                    "negative_count": 12,
                    "unique_candidate_count": 18,
                    "balanced_accuracy": balanced_accuracy,
                    "roc_auc": roc_auc,
                    "pairwise_comparison_count": 144,
                    "learned_pairwise_accuracy": 0.70,
                    "baseline_pairwise_accuracy": 0.60,
                    "pairwise_accuracy_delta": delta,
                }
            ]
        },
    }


def test_live_promotion_gate_passes_real_shadow_model(monkeypatch):
    monkeypatch.setattr(
        "services.class_recommendation.live_deployment.build_shadow_evaluation_report",
        lambda database, include_fixture_feedback=False: _shadow_report(),
    )

    report = build_live_promotion_report(FakeDatabase(), model_id=MODEL_ID)

    assert report["passed"] is True
    assert report["model"]["objective"] == "candidate_quality"
    assert report["ranking_policy"] == "candidate_quality_desc_then_baseline_rank"
    assert report["membership_effect"] == "none"
    assert all(check["passed"] for check in report["checks"])


def test_live_promotion_gate_blocks_pairwise_regression(monkeypatch):
    monkeypatch.setattr(
        "services.class_recommendation.live_deployment.build_shadow_evaluation_report",
        lambda database, include_fixture_feedback=False: _shadow_report(delta=-0.05),
    )

    report = build_live_promotion_report(FakeDatabase(), model_id=MODEL_ID)

    assert report["passed"] is False
    check = next(item for item in report["checks"] if item["name"] == "pairwise_vs_baseline")
    assert check["passed"] is False


def test_live_promotion_gate_rejects_membership_model(monkeypatch):
    monkeypatch.setattr(
        "services.class_recommendation.live_deployment.build_shadow_evaluation_report",
        lambda database, include_fixture_feedback=False: _shadow_report(),
    )

    report = build_live_promotion_report(
        FakeDatabase(objective="membership"),
        model_id=MODEL_ID,
    )

    assert report["passed"] is False
    objective = next(
        item for item in report["checks"] if item["name"] == "candidate_quality_objective"
    )
    assert objective["passed"] is False


def test_live_gate_config_rejects_invalid_thresholds():
    with pytest.raises(ValueError, match="min_samples"):
        LivePromotionGateConfig(min_samples=0)
    with pytest.raises(ValueError, match="min_roc_auc"):
        LivePromotionGateConfig(min_roc_auc=1.1)
