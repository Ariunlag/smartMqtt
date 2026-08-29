from contextlib import contextmanager
from types import SimpleNamespace

from services.class_recommendation.learning import (
    CANDIDATE_QUALITY_FEATURES,
    FEATURE_CONTRACT_VERSION,
    MEMBERSHIP_FEATURES,
)
from services.class_recommendation.model_registry import (
    ARTIFACT_FORMAT_VERSION,
    MODEL_TYPE,
)
from services.class_recommendation.shadow import RecommendationShadowScorer


def _artifact(objective: str, *, incompatible: bool = False):
    features = (
        MEMBERSHIP_FEATURES if objective == "membership" else CANDIDATE_QUALITY_FEATURES
    )
    coefficients = [0.0] * len(features)
    coefficients[0] = 2.0
    return {
        "artifact_format_version": ARTIFACT_FORMAT_VERSION,
        "model_type": MODEL_TYPE,
        "objective": objective,
        "feature_contract_version": (
            "incompatible-contract"
            if incompatible
            else FEATURE_CONTRACT_VERSION[objective]
        ),
        "feature_names": list(features),
        "dataset_fingerprint": "dataset",
        "source_feedback_ids": ["feedback"],
        "preprocessing": {
            "type": "standard_scaler",
            "mean": [0.0] * len(features),
            "scale": [1.0] * len(features),
            "variance": [1.0] * len(features),
        },
        "estimator": {
            "type": "logistic_regression",
            "classes": [0, 1],
            "coefficients": coefficients,
            "intercept": 0.0,
            "solver": "liblinear",
            "max_iter": 2000,
            "random_state": 42,
        },
    }


def _model(objective: str, *, incompatible: bool = False):
    return {
        "model_id": f"{objective}-model",
        "objective": objective,
        "model_version": 1,
        "feature_contract_version": FEATURE_CONTRACT_VERSION[objective],
        "artifact": _artifact(objective, incompatible=incompatible),
    }


def _topic_evidence(topic: str):
    return {
        "topic": topic,
        "channel_scores": {
            "items": [
                {"evidence_id": "key", "score": 0.9},
                {"evidence_id": "value", "score": 0.8},
                {"evidence_id": "key_value", "score": 0.85},
                {"evidence_id": "schema", "score": 0.95},
                {"evidence_id": "stream_context", "score": 0.7},
            ]
        },
        "coverage": {
            "candidate_coverage": 0.75,
            "prototype_coverage": 0.5,
        },
    }


def _snapshot():
    return {
        "candidate_id": "00000000-0000-0000-0000-000000000001",
        "candidate_version": 1,
        "strategy_id": "independent_hdbscan",
        "member_topics": ["topic/a", "topic/b"],
        "discovery_evidence": ["key", "value"],
        "snapshot_fingerprint": "snapshot-fp",
        "evidence_snapshot": {
            "strategy_id": "independent_hdbscan",
            "anchor_topic": "topic/a",
            "member_topics": ["topic/a", "topic/b"],
            "member_representation_versions": {"topic/a": 1, "topic/b": 1},
            "discovery_evidence": ["key", "value"],
            "topic_evidence": [_topic_evidence("topic/b")],
        },
    }


class FakeConnection:
    def __init__(self, database):
        self.database = database

    def execute(self, sql, params=()):
        normalized = " ".join(sql.split())
        assert normalized.startswith("INSERT INTO recommendation_shadow_observations")
        self.database.observations.append(params)
        return SimpleNamespace(rowcount=1)


class FakeDatabase:
    def __init__(self, models=None):
        self.models = models or {}
        self.observations = []

    def fetch_one(self, sql, params=()):
        normalized = " ".join(sql.split())
        assert "FROM recommendation_shadow_deployments d" in normalized
        return self.models.get(params[0])

    @contextmanager
    def transaction(self):
        yield FakeConnection(self)


class FakeCandidateStore:
    def __init__(self, snapshot=None):
        self.snapshot = snapshot or _snapshot()

    def get_snapshot(self, candidate_id, candidate_version):
        assert candidate_id == self.snapshot["candidate_id"]
        assert candidate_version == self.snapshot["candidate_version"]
        return self.snapshot


def _candidate_set():
    candidate = SimpleNamespace(
        candidate_id="00000000-0000-0000-0000-000000000001",
        candidate_version=1,
        rank=1,
        member_topics=("topic/a", "topic/b"),
    )
    return SimpleNamespace(
        candidates=(candidate,),
        strategy=SimpleNamespace(strategy_id="independent_hdbscan"),
    )


def test_shadow_scoring_preserves_baseline_and_persists_observation():
    database = FakeDatabase(
        {
            "membership": _model("membership"),
            "candidate_quality": _model("candidate_quality"),
        }
    )
    scorer = RecommendationShadowScorer(database, FakeCandidateStore())
    candidates = _candidate_set()

    result = scorer.evaluate(candidates)

    assert result["status"] == "scored"
    assert result["ranking_effect"] == "none"
    assert result["baseline_order_preserved"] is True
    assert candidates.candidates[0].rank == 1
    assert result["candidates"][0]["baseline_rank"] == 1
    assert result["candidates"][0]["candidate_quality_score"] > 0.5
    membership = result["candidates"][0]["membership_scores"]
    assert membership["topic/a"] == {
        "score": None,
        "reason": "topic_evidence_missing",
    }
    assert membership["topic/b"]["score"] > 0.5
    assert membership["topic/b"]["reason"] is None
    assert result["persistence"] == {"status": "stored", "count": 1}
    assert len(database.observations) == 1


def test_shadow_scoring_is_unavailable_without_explicit_deployment():
    database = FakeDatabase()
    scorer = RecommendationShadowScorer(database, FakeCandidateStore())

    result = scorer.evaluate(_candidate_set())

    assert result["status"] == "unavailable"
    assert result["reason"] == "no_shadow_active_models"
    assert result["ranking_effect"] == "none"
    assert database.observations == []


def test_incompatible_shadow_artifact_fails_partial_without_changing_baseline():
    database = FakeDatabase(
        {"membership": _model("membership", incompatible=True)}
    )
    scorer = RecommendationShadowScorer(database, FakeCandidateStore())
    candidates = _candidate_set()

    result = scorer.evaluate(candidates)

    assert result["status"] == "partial"
    assert candidates.candidates[0].rank == 1
    membership = result["candidates"][0]["membership_scores"]
    assert membership["topic/b"] == {
        "score": None,
        "reason": "model_incompatible",
    }
    assert result["persistence"]["status"] == "stored"
