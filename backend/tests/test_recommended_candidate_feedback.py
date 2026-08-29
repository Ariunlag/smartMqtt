from contextlib import contextmanager

import pytest

from services.class_recommendation.candidate_feedback import RecommendedCandidateStore
from services.class_recommendation.discovery import RecommendedClassDiscovery


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
        if normalized.startswith("SELECT strategy_id, current_version"):
            row = self.database.candidates.get(str(params[0]))
            return _Result(dict(row) if row else None)
        if normalized.startswith("INSERT INTO recommended_class_candidates"):
            candidate_id, strategy_id, version = params
            self.database.candidates[str(candidate_id)] = {
                "candidate_id": str(candidate_id),
                "strategy_id": strategy_id,
                "current_version": int(version),
            }
            return _Result()
        if normalized.startswith("SELECT snapshot_fingerprint"):
            candidate_id, version = params
            row = self.database.versions.get((str(candidate_id), int(version)))
            return _Result(
                {"snapshot_fingerprint": row["snapshot_fingerprint"]} if row else None
            )
        if normalized.startswith("INSERT INTO recommended_class_candidate_versions"):
            (
                candidate_id,
                version,
                member_json,
                discovery_json,
                evidence_json,
                fingerprint,
            ) = params
            import json

            self.database.versions[(str(candidate_id), int(version))] = {
                "candidate_id": str(candidate_id),
                "candidate_version": int(version),
                "member_topics": json.loads(member_json),
                "discovery_evidence": json.loads(discovery_json),
                "evidence_snapshot": json.loads(evidence_json),
                "snapshot_fingerprint": fingerprint,
                "created_at": None,
            }
            return _Result()
        if normalized.startswith("UPDATE recommended_class_candidates SET last_seen_at"):
            return _Result()
        if normalized.startswith("UPDATE recommended_class_candidates SET current_version"):
            version, candidate_id = params
            self.database.candidates[str(candidate_id)]["current_version"] = int(version)
            return _Result()
        raise AssertionError(normalized)


class FakeDatabase:
    def __init__(self):
        self.candidates = {}
        self.versions = {}
        self.feedback = []
        self.shadow = {}
        self.live = {}
        self.connection = FakeConnection(self)

    @contextmanager
    def transaction(self):
        yield self.connection

    def fetch_one(self, sql, params=()):
        normalized = " ".join(sql.split())
        if "FROM recommendation_shadow_observations" in normalized:
            candidate_id, version = params
            return self.shadow.get((str(candidate_id), int(version)))
        if "FROM recommendation_live_observations" in normalized:
            candidate_id, version = params
            return self.live.get((str(candidate_id), int(version)))

        assert "FROM recommended_class_candidates c" in normalized
        candidate_id, version = params
        candidate = self.candidates.get(str(candidate_id))
        snapshot = self.versions.get((str(candidate_id), int(version)))
        if candidate is None or snapshot is None:
            return None
        return {
            **snapshot,
            "strategy_id": candidate["strategy_id"],
        }

    def execute(self, sql, params=()):
        normalized = " ".join(sql.split())
        assert normalized.startswith("INSERT INTO recommended_class_feedback")
        self.feedback.append(params)
        return 1


def test_candidate_identity_is_stable_across_evidence_versions_and_strategy_specific():
    first = RecommendedClassDiscovery._candidate_id(("a", "b"), "independent_hdbscan")
    second = RecommendedClassDiscovery._candidate_id(("a", "b"), "independent_hdbscan")
    other_strategy = RecommendedClassDiscovery._candidate_id(("a", "b"), "tag_value_centroid")

    assert first == second
    assert first != other_strategy


def test_candidate_snapshot_version_only_increments_when_snapshot_changes():
    database = FakeDatabase()
    store = RecommendedCandidateStore(database)
    candidate_id = RecommendedClassDiscovery._candidate_id(("a", "b"), "independent_hdbscan")
    snapshot = {
        "strategy_id": "independent_hdbscan",
        "member_topics": ["a", "b"],
        "member_representation_versions": {"a": 1, "b": 1},
        "topic_evidence": [{"topic": "b", "score": 0.9}],
    }

    first = store.persist_snapshot(
        candidate_id=candidate_id,
        strategy_id="independent_hdbscan",
        member_topics=("a", "b"),
        discovery_evidence=("value",),
        evidence_snapshot=snapshot,
    )
    same = store.persist_snapshot(
        candidate_id=candidate_id,
        strategy_id="independent_hdbscan",
        member_topics=("a", "b"),
        discovery_evidence=("value",),
        evidence_snapshot=dict(snapshot),
    )
    changed_snapshot = {
        **snapshot,
        "member_representation_versions": {"a": 1, "b": 2},
    }
    changed = store.persist_snapshot(
        candidate_id=candidate_id,
        strategy_id="independent_hdbscan",
        member_topics=("a", "b"),
        discovery_evidence=("value",),
        evidence_snapshot=changed_snapshot,
    )

    assert (first, same, changed) == (1, 1, 2)
    assert database.candidates[candidate_id]["current_version"] == 2


def test_feedback_references_exact_version_and_copies_immutable_candidate_evidence():
    database = FakeDatabase()
    store = RecommendedCandidateStore(database)
    candidate_id = RecommendedClassDiscovery._candidate_id(("a", "b"), "tag_value_centroid")
    store.persist_snapshot(
        candidate_id=candidate_id,
        strategy_id="tag_value_centroid",
        member_topics=("a", "b"),
        discovery_evidence=("value",),
        evidence_snapshot={"topic_evidence": [{"topic": "b", "value_score": 0.95}]},
    )

    result = store.record_feedback(
        candidate_id=candidate_id,
        candidate_version=1,
        action_type="KEEP_TOPIC",
        topic="b",
    )

    assert result["candidate_version"] == 1
    assert result["action_type"] == "KEEP_TOPIC"
    assert result["topic"] == "b"
    assert result["shadow_observation_id"] is None
    assert result["live_observation_id"] is None
    assert len(database.feedback) == 1
    assert "candidate_evidence" in database.feedback[0][-3]
    assert database.feedback[0][-2:] == (None, None)

    with pytest.raises(ValueError, match="member"):
        store.record_feedback(
            candidate_id=candidate_id,
            candidate_version=1,
            action_type="REMOVE_TOPIC",
            topic="not-a-member",
        )


def test_feedback_links_latest_shadow_and_live_observations_when_available():
    database = FakeDatabase()
    store = RecommendedCandidateStore(database)
    candidate_id = RecommendedClassDiscovery._candidate_id(("a", "b"), "independent_hdbscan")
    store.persist_snapshot(
        candidate_id=candidate_id,
        strategy_id="independent_hdbscan",
        member_topics=("a", "b"),
        discovery_evidence=("key",),
        evidence_snapshot={"topic_evidence": [{"topic": "b"}]},
    )
    database.shadow[(candidate_id, 1)] = {
        "observation_id": "shadow-observation-1",
        "shadow_run_id": "shadow-run-1",
        "membership_model_id": "membership-model",
        "candidate_quality_model_id": None,
        "created_at": None,
    }
    database.live[(candidate_id, 1)] = {
        "observation_id": "live-observation-1",
        "live_run_id": "live-run-1",
        "model_id": "quality-model",
        "baseline_rank": 2,
        "live_rank": 1,
        "created_at": None,
    }

    result = store.record_feedback(
        candidate_id=candidate_id,
        candidate_version=1,
        action_type="KEEP_TOPIC",
        topic="b",
    )

    assert result["shadow_observation_id"] == "shadow-observation-1"
    assert result["live_observation_id"] == "live-observation-1"
    assert database.feedback[0][-2] == "shadow-observation-1"
    assert database.feedback[0][-1] == "live-observation-1"
    assert "shadow-observation-1" in database.feedback[0][-3]
    assert "live-observation-1" in database.feedback[0][-3]


def test_candidate_level_feedback_rejects_topic_payload():
    database = FakeDatabase()
    store = RecommendedCandidateStore(database)
    with pytest.raises(ValueError, match="does not accept"):
        store.record_feedback(
            candidate_id="00000000-0000-0000-0000-000000000000",
            candidate_version=1,
            action_type="ACCEPT_CANDIDATE",
            topic="a",
        )
