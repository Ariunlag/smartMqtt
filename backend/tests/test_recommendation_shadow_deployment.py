from contextlib import contextmanager

import pytest

from services.class_recommendation.shadow_deployment import (
    RecommendationShadowDeploymentRegistry,
    shadow_activation_allowed,
)


class _Result:
    def __init__(self, row=None):
        self.row = row

    def fetchone(self):
        return self.row


class FakeConnection:
    def __init__(self, database):
        self.database = database

    def execute(self, sql, params=()):
        normalized = " ".join(sql.split())
        if normalized.startswith("SELECT model_id::text AS model_id, objective"):
            return _Result(self.database.models.get(str(params[0])))
        if normalized.startswith("SELECT pg_advisory_xact_lock"):
            return _Result()
        if normalized.startswith("SELECT objective, model_id::text AS model_id"):
            objective = str(params[0])
            model_id = self.database.deployments.get(objective)
            return _Result(
                {"objective": objective, "model_id": model_id}
                if model_id is not None
                else None
            )
        if normalized.startswith("DELETE FROM recommendation_shadow_deployments"):
            self.database.deployments.pop(str(params[0]), None)
            return _Result()
        if normalized.startswith("INSERT INTO recommendation_shadow_deployments"):
            objective, model_id, reason = params
            self.database.deployments[str(objective)] = str(model_id)
            self.database.activation_reasons[str(objective)] = str(reason)
            return _Result()
        if normalized.startswith("INSERT INTO recommendation_shadow_deployment_events"):
            self.database.events.append(params)
            return _Result()
        raise AssertionError(normalized)


class FakeDatabase:
    def __init__(self, models):
        self.models = {str(row["model_id"]): dict(row) for row in models}
        self.deployments = {}
        self.activation_reasons = {}
        self.events = []

    @contextmanager
    def transaction(self):
        yield FakeConnection(self)


def _model(model_id: str, *, status="OFFLINE_APPROVED", version=1):
    return {
        "model_id": model_id,
        "objective": "membership",
        "model_version": version,
        "status": status,
    }


def test_shadow_activation_requires_offline_approval():
    allowed, reason = shadow_activation_allowed(_model("candidate", status="CANDIDATE"))
    assert allowed is False
    assert "OFFLINE_APPROVED" in reason

    database = FakeDatabase([_model("candidate", status="CANDIDATE")])
    registry = RecommendationShadowDeploymentRegistry(database)
    with pytest.raises(ValueError, match="OFFLINE_APPROVED"):
        registry.activate(model_id="candidate", reason="test")


def test_shadow_activation_is_explicit_idempotent_and_audited():
    database = FakeDatabase([_model("model-1")])
    registry = RecommendationShadowDeploymentRegistry(database)

    first = registry.activate(model_id="model-1", reason="shadow evaluation")
    second = registry.activate(model_id="model-1", reason="repeat")

    assert first == {
        "objective": "membership",
        "model_id": "model-1",
        "model_version": 1,
        "state": "SHADOW_ACTIVE",
        "changed": True,
        "ranking_effect": "none",
    }
    assert second["changed"] is False
    assert database.deployments == {"membership": "model-1"}
    assert database.activation_reasons["membership"] == "shadow evaluation"
    assert len(database.events) == 1
    assert database.events[0][3] == "ACTIVATED"


def test_shadow_replacement_and_deactivation_are_audited():
    database = FakeDatabase([_model("model-1"), _model("model-2", version=2)])
    registry = RecommendationShadowDeploymentRegistry(database)

    registry.activate(model_id="model-1", reason="first")
    replacement = registry.activate(model_id="model-2", reason="better offline model")
    deactivated = registry.deactivate(
        objective="membership",
        reason="finish shadow run",
    )
    repeated = registry.deactivate(objective="membership", reason="already stopped")

    assert replacement["model_id"] == "model-2"
    assert replacement["changed"] is True
    assert deactivated["state"] == "SHADOW_INACTIVE"
    assert deactivated["changed"] is True
    assert repeated["changed"] is False
    assert database.deployments == {}
    assert [event[3] for event in database.events] == [
        "ACTIVATED",
        "DEACTIVATED",
        "ACTIVATED",
        "DEACTIVATED",
    ]
