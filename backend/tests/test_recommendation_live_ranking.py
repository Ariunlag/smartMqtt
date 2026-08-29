from contextlib import contextmanager

from services.class_recommendation.discovery import (
    RecommendedClassCandidate,
    RecommendedClassCandidateSet,
)
from services.class_recommendation.learning import CANDIDATE_QUALITY_FEATURES
from services.class_recommendation.live_ranking import RecommendationLiveRanker
from services.class_recommendation.model_registry import (
    ARTIFACT_FORMAT_VERSION,
    MODEL_TYPE,
)
from services.class_recommendation.strategies import STRATEGY_DEFINITIONS


class _Result:
    def fetchone(self):
        return None


class _Connection:
    def __init__(self, database):
        self.database = database

    def execute(self, sql, params=()):
        normalized = " ".join(sql.split())
        if normalized.startswith("INSERT INTO recommendation_live_observations"):
            self.database.observations.append(params)
            return _Result()
        raise AssertionError(normalized)


class FakeDatabase:
    def __init__(self, model=None):
        self.model = model
        self.observations = []
        self.connection = _Connection(self)

    def fetch_one(self, sql, params=()):
        normalized = " ".join(sql.split())
        if "FROM recommendation_live_deployments" in normalized:
            return self.model
        raise AssertionError(normalized)

    @contextmanager
    def transaction(self):
        yield self.connection


class FakeCandidateStore:
    def __init__(self, snapshots):
        self.snapshots = snapshots

    def get_snapshot(self, candidate_id, candidate_version):
        return self.snapshots.get((candidate_id, candidate_version))


def _artifact(member_count_coefficient=1.0):
    features = list(CANDIDATE_QUALITY_FEATURES)
    coefficients = [0.0] * len(features)
    coefficients[features.index("member_count")] = member_count_coefficient
    return {
        "artifact_format_version": ARTIFACT_FORMAT_VERSION,
        "model_type": MODEL_TYPE,
        "objective": "candidate_quality",
        "feature_contract_version": "candidate-quality-evidence-v1",
        "feature_names": features,
        "dataset_fingerprint": "fixture",
        "source_feedback_ids": [],
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


def _model(artifact=None):
    return {
        "model_id": "00000000-0000-0000-0000-000000000111",
        "objective": "candidate_quality",
        "model_version": 7,
        "feature_contract_version": "candidate-quality-evidence-v1",
        "artifact": artifact or _artifact(),
    }


def _candidate(candidate_id, rank, members):
    return RecommendedClassCandidate(
        candidate_id=candidate_id,
        candidate_version=1,
        rank=rank,
        anchor_topic=members[0],
        member_topics=tuple(members),
        discovery_channels=("value",),
        evidence=(),
    )


def _snapshot(candidate_id, members):
    topic_evidence = [
        {
            "topic": topic,
            "channel_scores": {"items": []},
            "coverage": {
                "candidate_coverage": 0.5,
                "prototype_coverage": 0.5,
            },
        }
        for topic in members[1:]
    ]
    return {
        "candidate_id": candidate_id,
        "candidate_version": 1,
        "strategy_id": "independent_hdbscan",
        "member_topics": list(members),
        "discovery_evidence": ["value"],
        "snapshot_fingerprint": f"fp-{candidate_id}",
        "evidence_snapshot": {
            "strategy_id": "independent_hdbscan",
            "member_topics": list(members),
            "discovery_evidence": ["value"],
            "topic_evidence": topic_evidence,
        },
    }


def _candidate_set():
    first = _candidate("00000000-0000-0000-0000-000000000001", 1, ("a", "b"))
    second = _candidate(
        "00000000-0000-0000-0000-000000000002", 2, ("c", "d", "e")
    )
    return RecommendedClassCandidateSet(
        candidates=(first, second),
        available_topics=("a", "b", "c", "d", "e"),
        strategy=STRATEGY_DEFINITIONS[0],
    )


def test_live_ranker_is_noop_without_active_model():
    candidate_set = _candidate_set()
    ranker = RecommendationLiveRanker(FakeDatabase(), FakeCandidateStore({}))

    result, metadata = ranker.apply(candidate_set)

    assert result == candidate_set
    assert metadata["status"] == "baseline"
    assert metadata["ranking_effect"] == "baseline"


def test_live_ranker_reorders_candidates_without_changing_membership():
    candidate_set = _candidate_set()
    snapshots = {
        (candidate.candidate_id, 1): _snapshot(candidate.candidate_id, candidate.member_topics)
        for candidate in candidate_set.candidates
    }
    database = FakeDatabase(_model())
    ranker = RecommendationLiveRanker(database, FakeCandidateStore(snapshots))

    result, metadata = ranker.apply(candidate_set)

    assert [item.candidate_id for item in result.candidates] == [
        candidate_set.candidates[1].candidate_id,
        candidate_set.candidates[0].candidate_id,
    ]
    assert result.candidates[0].member_topics == candidate_set.candidates[1].member_topics
    assert result.candidates[1].member_topics == candidate_set.candidates[0].member_topics
    assert [item.rank for item in result.candidates] == [1, 2]
    assert metadata["status"] == "applied"
    assert metadata["ranking_effect"] == "candidate_reorder"
    assert metadata["membership_effect"] == "none"
    assert len(database.observations) == 2


def test_live_ranker_falls_back_for_incompatible_artifact():
    candidate_set = _candidate_set()
    snapshots = {
        (candidate.candidate_id, 1): _snapshot(candidate.candidate_id, candidate.member_topics)
        for candidate in candidate_set.candidates
    }
    artifact = _artifact()
    artifact["feature_contract_version"] = "future-contract"
    database = FakeDatabase(_model(artifact))
    ranker = RecommendationLiveRanker(database, FakeCandidateStore(snapshots))

    result, metadata = ranker.apply(candidate_set)

    assert result == candidate_set
    assert metadata["status"] == "fallback"
    assert metadata["ranking_effect"] == "baseline_fallback"
    assert database.observations == []
