from services.class_recommendation.learning import RecommendationFeedbackDatasetBuilder


def _snapshot(strategy: str):
    return {
        "strategy_id": strategy,
        "member_topics": ["topic/a", "topic/b"],
        "discovery_evidence": ["value"],
        "candidate_evidence": {
            "strategy_id": strategy,
            "member_topics": ["topic/a", "topic/b"],
            "discovery_evidence": ["value"],
            "topic_evidence": [
                {
                    "topic": "topic/b",
                    "channel_scores": {
                        "items": [
                            {"evidence_id": "key", "score": 0.8},
                            {"evidence_id": "value", "score": 0.9},
                            {"evidence_id": "key_value", "score": 0.85},
                            {"evidence_id": "schema", "score": 0.95},
                            {"evidence_id": "stream_context", "score": 0.7},
                        ]
                    },
                    "coverage": {
                        "candidate_coverage": 1.0,
                        "prototype_coverage": 1.0,
                    },
                }
            ],
        },
    }


class FakeDatabase:
    def fetch_all(self, sql, params=()):
        del sql, params
        return [
            {
                "feedback_id": "1",
                "candidate_id": "candidate-hdbscan",
                "candidate_version": 1,
                "action_type": "ACCEPT_CANDIDATE",
                "topic": None,
                "evidence_snapshot": _snapshot("independent_hdbscan"),
                "occurred_at": 1,
            },
            {
                "feedback_id": "2",
                "candidate_id": "candidate-centroid",
                "candidate_version": 1,
                "action_type": "DISMISS_CANDIDATE",
                "topic": None,
                "evidence_snapshot": _snapshot("tag_value_centroid"),
                "occurred_at": 2,
            },
        ]


def test_same_member_set_is_one_evaluation_group_across_strategies():
    quality = RecommendationFeedbackDatasetBuilder(FakeDatabase()).build()[
        "candidate_quality"
    ]

    assert len(quality.examples) == 2
    assert quality.examples[0].candidate_id != quality.examples[1].candidate_id
    assert len(set(quality.groups)) == 1
