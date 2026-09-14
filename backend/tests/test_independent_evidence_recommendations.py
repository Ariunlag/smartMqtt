import pytest

from services.class_recommendation.discovery import RecommendedClassDiscovery
from services.class_recommendation.processing import RecommendationObservationFanout
from services.class_recommendation.strategies import (
    HdbscanStrategyConfig,
    IndependentEvidenceHdbscanStrategy,
    RecommendationStrategyInput,
)


def test_identical_membership_from_different_evidence_stays_separate():
    topics = ("topic/a", "topic/b", "topic/c")
    symmetric_scores = {
        ("topic/a", "topic/b"): {
            "key": 0.99,
            "value": 0.99,
            "key_value": 0.10,
            "schema": 0.10,
            "stream_context": 0.10,
        },
        ("topic/a", "topic/c"): {
            "key": 0.10,
            "value": 0.10,
            "key_value": 0.10,
            "schema": 0.10,
            "stream_context": 0.10,
        },
        ("topic/b", "topic/c"): {
            "key": 0.10,
            "value": 0.10,
            "key_value": 0.10,
            "schema": 0.10,
            "stream_context": 0.10,
        },
    }

    def cluster_labels(evidence_id, matrix):
        del matrix
        if evidence_id in {"key", "value"}:
            return (0, 0, -1)
        return (-1, -1, -1)

    strategy = IndependentEvidenceHdbscanStrategy(
        HdbscanStrategyConfig(min_cluster_size=2),
        cluster_labels=cluster_labels,
    )
    groups = strategy.discover(
        RecommendationStrategyInput(
            topics=topics,
            versions={topic: 1 for topic in topics},
            pairs_by_topic={topic: () for topic in topics},
            stream_vectors={topic: None for topic in topics},
            symmetric_scores=symmetric_scores,
        )
    )

    assert [group.members for group in groups] == [
        ("topic/a", "topic/b"),
        ("topic/a", "topic/b"),
    ]
    assert [group.evidence_ids for group in groups] == [("key",), ("value",)]


def test_candidate_identity_includes_discovery_evidence():
    members = ("topic/a", "topic/b")
    key_id = RecommendedClassDiscovery._candidate_id(
        members,
        "independent_hdbscan",
        ("key",),
    )
    value_id = RecommendedClassDiscovery._candidate_id(
        members,
        "independent_hdbscan",
        ("value",),
    )
    repeated_key_id = RecommendedClassDiscovery._candidate_id(
        members,
        "independent_hdbscan",
        ("key",),
    )

    assert key_id != value_id
    assert key_id == repeated_key_id


@pytest.mark.asyncio
async def test_observation_fanout_keeps_primary_pipeline_authoritative(caplog):
    calls = []

    class Primary:
        async def observe(self, message):
            calls.append(("primary", message))
            return "primary-result"

    class Secondary:
        async def observe(self, message):
            calls.append(("secondary", message))
            raise RuntimeError("experimental failure")

    message = object()
    fanout = RecommendationObservationFanout(Primary(), Secondary())

    assert await fanout.observe(message) == "primary-result"
    assert calls == [("primary", message), ("secondary", message)]
    assert "Secondary recommendation observer failed" in caplog.text
