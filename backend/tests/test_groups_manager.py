from services.class_recommendation.domain import (
    PairEmbeddingRecord,
    PairIdentity,
    PairRepresentation,
)
from services.groups_manager import GroupManager


def _record(topic, source, key, datatype, *, key_vector, value_vector):
    identity = PairIdentity(source, key, datatype)
    representation = PairRepresentation(
        canonical_topic=topic,
        original_topic=topic,
        identity=identity,
        raw_key=key,
        raw_value="fixture-value",
        normalized_key=key,
        normalized_value="fixture value",
        datatype=datatype,
        representation_version=1,
        texts=(
            ("key", key),
            ("value", "fixture value"),
            ("key_value", f"{key}: fixture value"),
            ("schema", f"{key}: {datatype}"),
        ),
    )
    return PairEmbeddingRecord(
        representation=representation,
        vectors=(
            ("key", tuple(key_vector)),
            ("value", tuple(value_vector)),
            ("key_value", (0.3, 0.7)),
            ("schema", (0.4, 0.6)),
        ),
    )


class FakeTagSetStore:
    def __init__(self):
        self.calls = []

    def find_or_create_set(self, tag_key, tag_value, vector, threshold, topic):
        self.calls.append(
            {
                "tag_key": tag_key,
                "tag_value": tag_value,
                "vector": vector,
                "threshold": threshold,
                "topic": topic,
            }
        )
        return "set_1"

    def get_all(self):
        return []


async def test_tag_grouping_reuses_only_shared_tag_value_evidence(monkeypatch):
    fake_store = FakeTagSetStore()
    monkeypatch.setattr("services.groups_manager.tagset_store", fake_store)

    tag = _record(
        "topic/a",
        "tag",
        "location",
        "string",
        key_vector=(1.0, 0.0),
        value_vector=(0.0, 1.0),
    )
    field = _record(
        "topic/a",
        "field",
        "temperature",
        "numeric",
        key_vector=(0.8, 0.2),
        value_vector=(0.7, 0.3),
    )

    await GroupManager(threshold=0.85).update_from_pair_evidence(
        "topic/a",
        (tag, field),
    )

    assert fake_store.calls == [
        {
            "tag_key": "location",
            "tag_value": "fixture-value",
            "vector": [0.0, 1.0],
            "threshold": 0.85,
            "topic": "topic/a",
        }
    ]
