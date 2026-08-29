from contextlib import contextmanager

import pytest

from services.class_recommendation.live_deployment import (
    LivePromotionGateConfig,
    RecommendationLiveDeploymentRegistry,
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


class _Result:
    def __init__(self, row=None):
        self.row = row

    def fetchone(self):
        return self.row


class _LifecycleConnection:
    def __init__(self, database):
        self.database = database

    def execute(self, sql, params=()):
        normalized = " ".join(sql.split())
        if normalized.startswith("SELECT pg_advisory_xact_lock"):
            return _Result()
        if normalized.startswith("SELECT model_id::text AS model_id FROM recommendation_live_deployments"):
            return _Result(
                {"model_id": self.database.current_model}
                if self.database.current_model
                else None
            )
        if normalized.startswith("DELETE FROM recommendation_live_deployments"):
            self.database.current_model = None
            return _Result()
        if normalized.startswith("INSERT INTO recommendation_live_deployments"):
            model_id, _report, _reason = params
            self.database.current_model = str(model_id)
            return _Result()
        if normalized.startswith("INSERT INTO recommendation_live_deployment_events"):
            self.database.events.append(params)
            return _Result()
        raise AssertionError(normalized)


class LifecycleDatabase:
    def __init__(self):
        self.current_model = None
        self.events = []
        self.connection = _LifecycleConnection(self)

    @contextmanager
    def transaction(self):
        yield self.connection


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


def _passing_promotion_report():
    return {
        "passed": True,
        "model": {
            "model_id": MODEL_ID,
            "model_version": 4,
            "objective": "candidate_quality",
            "feature_contract_version": "candidate-quality-evidence-v1",
            "status": "OFFLINE_APPROVED",
        },
        "checks": [],
        "ranking_policy": "candidate_quality_desc_then_baseline_rank",
        "membership_effect": "none",
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


def test_live_activation_and_rollback_are_explicit_and_audited(monkeypatch):
    database = LifecycleDatabase()
    registry = RecommendationLiveDeploymentRegistry(database)
    monkeypatch.setattr(
        registry,
        "check",
        lambda model_id, config=None: _passing_promotion_report(),
    )

    activated = registry.activate(model_id=MODEL_ID, reason="shadow gate passed")

    assert activated["state"] == "LIVE_ACTIVE"
    assert activated["ranking_effect"] == "candidate_reorder"
    assert database.current_model == MODEL_ID
    assert len(database.events) == 1

    rolled_back = registry.rollback(reason="manual safety rollback")

    assert rolled_back["state"] == "BASELINE_ACTIVE"
    assert rolled_back["ranking_effect"] == "baseline"
    assert database.current_model is None
    assert len(database.events) == 2
