from services.class_recommendation.learning import (
    MEMBERSHIP_FEATURES,
    TrainingDataset,
    TrainingExample,
    RecommendationFeedbackDatasetBuilder,
    train_offline_report,
)


def _topic_evidence(topic: str, key_score: float, value_score: float):
    return {
        "topic": topic,
        "channel_scores": {
            "items": [
                {"evidence_id": "key", "score": key_score},
                {"evidence_id": "value", "score": value_score},
                {"evidence_id": "key_value", "score": (key_score + value_score) / 2},
                {"evidence_id": "schema", "score": 0.9},
                {"evidence_id": "stream_context", "score": 0.8},
            ]
        },
        "coverage": {
            "candidate_coverage": 0.75,
            "prototype_coverage": 0.5,
            "candidate_pair_count": 4,
            "class_prototype_count": 4,
            "matched_pair_count": 3,
        },
        "matched_pairs": [],
        "duplicate_pending": False,
    }


def _snapshot(*, members=("a", "b"), evidence=None, strategy="independent_hdbscan"):
    if evidence is None:
        evidence = [_topic_evidence("b", 0.9, 0.8)]
    return {
        "candidate_id": "00000000-0000-0000-0000-000000000001",
        "candidate_version": 1,
        "strategy_id": strategy,
        "member_topics": list(members),
        "discovery_evidence": ["key", "value"],
        "snapshot_fingerprint": "fp",
        "candidate_evidence": {
            "strategy_id": strategy,
            "member_topics": list(members),
            "discovery_evidence": ["key", "value"],
            "topic_evidence": evidence,
        },
    }


class FakeDatabase:
    def __init__(self, rows):
        self.rows = rows

    def fetch_all(self, sql, params=()):
        assert "FROM recommended_class_feedback" in " ".join(sql.split())
        assert params == ()
        return list(self.rows)


def _row(
    feedback_id,
    action,
    *,
    candidate_id="00000000-0000-0000-0000-000000000001",
    topic=None,
    snapshot=None,
    order=0,
):
    return {
        "feedback_id": feedback_id,
        "candidate_id": candidate_id,
        "candidate_version": 1,
        "action_type": action,
        "topic": topic,
        "evidence_snapshot": snapshot or _snapshot(),
        "occurred_at": order,
    }


def test_builder_uses_latest_explicit_label_and_skips_anchor_without_inventing_features():
    rows = [
        _row("1", "KEEP_TOPIC", topic="b", order=1),
        _row("2", "REMOVE_TOPIC", topic="b", order=2),
        _row("3", "KEEP_TOPIC", topic="a", order=3),
        _row("4", "ACCEPT_CANDIDATE", order=4),
        _row("5", "DISMISS_CANDIDATE", order=5),
    ]
    datasets = RecommendationFeedbackDatasetBuilder(FakeDatabase(rows)).build()

    membership = datasets["membership"]
    assert len(membership.examples) == 1
    assert membership.examples[0].target == "b"
    assert membership.examples[0].label == 0
    assert membership.skipped_by_reason == {"topic_evidence_missing": 1}
    assert len(membership.examples[0].features) == len(MEMBERSHIP_FEATURES)
    assert membership.examples[0].features[0] == 0.9
    assert membership.examples[0].features[5] == 1.0

    quality = datasets["candidate_quality"]
    assert len(quality.examples) == 1
    assert quality.examples[0].label == 0


def test_offline_report_refuses_single_class_feedback():
    dataset = TrainingDataset(
        objective="membership",
        feature_names=("key_score",),
        examples=(
            TrainingExample(
                feedback_id="1",
                candidate_id="c1",
                candidate_version=1,
                strategy_id="independent_hdbscan",
                objective="membership",
                target="a",
                label=1,
                features=(0.9,),
            ),
        ),
        skipped_by_reason={},
    )

    report = train_offline_report(dataset)
    assert report["status"] == "not_trainable"
    assert report["feature_contract_version"] == "membership-evidence-v1"
    assert report["promotion"] == "none"
    assert report["cross_validation"]["status"] == "not_available"


def test_offline_report_fits_coefficients_and_uses_candidate_grouped_evaluation():
    examples = []
    for index, (candidate_id, label, score) in enumerate(
        (
            ("positive-a", 1, 0.95),
            ("positive-a", 1, 0.90),
            ("positive-b", 1, 0.85),
            ("positive-b", 1, 0.80),
            ("negative-a", 0, 0.20),
            ("negative-a", 0, 0.25),
            ("negative-b", 0, 0.30),
            ("negative-b", 0, 0.35),
        )
    ):
        examples.append(
            TrainingExample(
                feedback_id=str(index),
                candidate_id=candidate_id,
                candidate_version=1,
                strategy_id="independent_hdbscan",
                objective="membership",
                target=f"topic-{index}",
                label=label,
                features=(score, 1.0),
            )
        )

    dataset = TrainingDataset(
        objective="membership",
        feature_names=("key_score", "has_key"),
        examples=tuple(examples),
        skipped_by_reason={},
    )
    report = train_offline_report(dataset)

    assert report["status"] == "trained_offline"
    assert report["feature_contract_version"] == "membership-evidence-v1"
    assert report["promotion"] == "none"
    assert set(report["standardized_coefficients"]) == {"key_score", "has_key"}
    assert report["standardized_coefficients"]["key_score"] > 0
    assert report["cross_validation"]["status"] == "available"
    assert report["cross_validation"]["folds"] == 2
