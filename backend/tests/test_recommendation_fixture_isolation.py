from api.recommendations import _FilteredRecommendationMetadata


class FakeMetadataStore:
    def __init__(self):
        self.rows = {
            "real/site/temperature": {"canonical_topic": "real/site/temperature"},
            "acceptance/run1/temperature": {
                "canonical_topic": "acceptance/run1/temperature"
            },
        }

    def all_topic_states(self):
        return list(self.rows.values())

    def topic_state(self, topic):
        return self.rows.get(topic)


def test_user_facing_metadata_excludes_acceptance_namespace():
    view = _FilteredRecommendationMetadata(FakeMetadataStore(), ("acceptance/",))

    assert [row["canonical_topic"] for row in view.all_topic_states()] == [
        "real/site/temperature"
    ]
    assert view.topic_state("acceptance/run1/temperature") is None
    assert view.topic_state("real/site/temperature") == {
        "canonical_topic": "real/site/temperature"
    }


def test_acceptance_stack_can_explicitly_disable_topic_filter():
    view = _FilteredRecommendationMetadata(FakeMetadataStore(), ())

    assert {row["canonical_topic"] for row in view.all_topic_states()} == {
        "real/site/temperature",
        "acceptance/run1/temperature",
    }
