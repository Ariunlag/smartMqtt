import copy
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from services.class_recommendation.adaptive import AdaptiveRecommendations, RevisionConflict
from services.class_recommendation.adaptive_evidence import (
    CachedEncoder, ProviderDefinition, ProviderRegistry, TextProvider, weighted_score,
)
from services.class_recommendation.adaptive_learning import baseline, effective_labels, train


class MemoryStore:
    def __init__(self):
        self.rows = {}
        self.vectors = {}
        self.saved_groups = {}
        self.saved_events = []
        self.saved_models = {}
        self.saved_classes = {}

    @contextmanager
    def transaction(self):
        before = copy.deepcopy(self.__dict__)
        try:
            yield self
        except Exception:
            self.__dict__.update(before)
            raise

    def topics(self):
        return list(self.rows.values())

    def topic_fingerprint(self, topic):
        return self.rows.get(topic, {}).get("fingerprint")

    def material(self):
        return copy.deepcopy(self.vectors)

    def replace_material(self, topic, tags, fingerprint, records):
        self.rows[topic] = dict(topic=topic, tags=tags, fingerprint=fingerprint)
        self.vectors[topic] = {}
        for record in records:
            self.vectors[topic].setdefault(record["provider_id"], []).append(copy.deepcopy(record))

    def groups(self, conn=None):
        return copy.deepcopy(list(self.saved_groups.values()))

    def put_group(self, conn, state):
        self.saved_groups[state["group_id"]] = copy.deepcopy(state)

    def event(self, conn, event):
        self.saved_events.append(dict(copy.deepcopy(event), sequence=len(self.saved_events)+1))

    def events(self):
        return copy.deepcopy(self.saved_events)

    def model(self, manifest):
        return copy.deepcopy(self.saved_models.get(manifest))

    def put_model(self, manifest, model):
        model["version"] = self.saved_models.get(manifest, {}).get("version", 0)+1
        self.saved_models[manifest] = copy.deepcopy(model)

    def classes(self, conn=None):
        return copy.deepcopy(list(self.saved_classes.values()))

    def save_class(self, conn, name, members, class_id):
        current = self.saved_classes.get(name)
        if current and current["class_id"] != class_id:
            raise ValueError("A different Class already uses this name")
        row = dict(name=name, topics=list(members), class_id=class_id,
                   profile_version=current["profile_version"]+1 if current else 1)
        self.saved_classes[name] = row
        return row

    def delete_class(self, conn, name):
        return self.saved_classes.pop(name, None) is not None

    def bootstrap_tags(self):
        return []


class Model:
    def __init__(self):
        self.calls = []

    def encode(self, texts):
        self.calls.append(list(texts))
        return [[1., 0., 0.] for _ in texts]


class Identities:
    def __init__(self):
        self.aliases = {}

    def resolve_canonical(self, topic):
        return self.aliases.get(topic, topic)

    def resolve_many(self, topics):
        return {t: self.resolve_canonical(t) for t in topics}


def service(environment="lab"):
    return AdaptiveRecommendations(Model(), Identities(), store=MemoryStore(), environment_id=environment)


def seed(svc):
    for topic in ("a", "b", "c"):
        svc.materialize(topic, {"sensor_type": "temperature", "location": "lab"})
    svc._discover = lambda material, model: [svc._new_group("suggestion", ["a", "b"])]
    return svc.recommendations()["groups"][0]


async def test_four_channels_are_tag_only_and_numeric_fields_do_not_reembed():
    svc = service()
    message = SimpleNamespace(topic="building/lab/a", tags={"sensor_type": "temperature", "offset": -5}, fields={"reading": 23})
    assert await svc.observe(message)
    records = [r for rows in svc.store.vectors[message.topic].values() for r in rows]
    assert len(records) == 7
    assert {r["provider_id"] for r in records} == set(svc.registry.active_ids)
    assert len(svc.encoder.model.calls) == 1
    assert svc.store.vectors[message.topic]["topic_text"][0]["payload"]["text"] == "building lab a"
    assert "offset: -5" in svc.encoder.model.calls[0]
    message.fields = {"reading": 99, "humidity": 80}
    assert not await svc.observe(message)
    assert len(svc.encoder.model.calls) == 1
    # A newly constructed process recognizes persisted input fingerprints.
    restarted = service()
    restarted.store = svc.store
    assert not await restarted.observe(message)
    assert restarted.encoder.model.calls == []


def test_encoder_handles_batches_larger_than_cache_without_losing_results():
    encoder = CachedEncoder(Model(), maxsize=2)
    assert len(encoder(["a", "b", "c", "a"])) == 4
    assert len(encoder.cached) == 2
    assert encoder(["c"])[0] == [1., 0., 0.]
    assert len(encoder.model.calls) == 1


def test_missing_channel_is_not_zero_and_shadow_does_not_change_weights():
    registry = ProviderRegistry()
    manifest = registry.manifest_id

    class NumericProvider:
        definition = ProviderDefinition("series_shape", "Series shape", "series_window", kind="direct_similarity")

        def materialize(self, topic, tags, encode):
            return []

        def compare(self, left, right):
            return dict(score=None, status="warming", coverage=0, matches=[])

    registry.register(NumericProvider())
    assert registry.manifest_id == manifest
    assert registry.catalog()[-1]["active"] is False
    weights = {"topic_text": .25, "tag_key": .25, "tag_value": .25, "tag_key_value": .25}
    evidence = {"topic_text": dict(score=.8, status="available", coverage=1),
                "tag_key": dict(score=None, status="missing", coverage=0)}
    assert weighted_score(evidence, weights) == pytest.approx(.8)
    assert weighted_score({}, weights) is None


def test_different_vector_dimensions_are_valid_in_separate_provider_spaces():
    a = TextProvider("topic_text", "Topic", "stream")
    b = TextProvider("tag_key", "Key", "pair")
    registry = ProviderRegistry([a, b])
    def row(vector):
        return [{"embedding": vector, "payload": {"text": "x"}}]
    material = {"topic_text": row([1, 0]), "tag_key": row([1, 0, 0, 0, 0])}
    assert all(e["score"] == 1 for e in registry.compare(material, material).values())
    broken = copy.deepcopy(material)
    broken["tag_key"][0]["provider_version"] = "2"
    assert registry.compare(material, broken)["tag_key"]["status"] == "incompatible"
    broken["tag_key"] = row([1, 0])
    result = registry.compare(material, broken)
    assert result["tag_key"]["status"] == "incompatible"
    assert result["topic_text"]["score"] == 1


def test_pair_text_provider_keeps_only_strong_semantic_matches():
    provider = TextProvider("tag_value", "Tag values", "pair", min_match_similarity=0.75)

    left = [
        {"embedding": [1.0, 0.0], "payload": {"text": "Chicago"}},
        {"embedding": [0.0, 1.0], "payload": {"text": "lecture room"}},
    ]
    right = [
        {"embedding": [1.0, 0.0], "payload": {"text": "Chicago"}},
        {"embedding": [0.0, -1.0], "payload": {"text": "emergency care"}},
    ]

    result = provider.compare(left, right)

    assert result["status"] == "available"
    assert result["score"] == pytest.approx(1.0)
    assert result["coverage"] == pytest.approx(0.5)
    assert result["matches"] == [
        {
            "left": {"text": "Chicago"},
            "right": {"text": "Chicago"},
            "similarity": pytest.approx(1.0),
        }
    ]


def test_model_change_masks_old_vectors_until_rematerialized():
    svc = service()
    svc.materialize("a", {"sensor": "temperature"})
    material = svc.store.material()["a"]
    other = ProviderRegistry(model_id="different-model")
    assert all(e["status"] == "incompatible" for e in other.compare(material, material).values())


def test_custom_provider_materializes_once_and_invalid_scores_are_unavailable():
    class Custom:
        definition = ProviderDefinition("custom", "Custom", "stream")
        calls = 0

        def materialize(self, topic, tags, encode):
            self.calls += 1
            return [{"entity": "custom", "embedding": [1, 0], "payload": {}}]

        def compare(self, left, right):
            return {"status": "available", "score": float("nan"), "coverage": 1}

    svc = service()
    custom = Custom()
    svc.registry.register(custom)
    svc.materialize("a", {})
    assert custom.calls == 1
    material = svc.store.material()["a"]
    assert svc.registry.compare(material, material)["custom"]["status"] == "incompatible"


def test_edit_remove_add_undo_refresh_and_saved_class_are_durable():
    svc = service()
    group = seed(svc)
    removed = svc.edit(group["group_id"], "remove", group["revision"], topic="b")
    assert removed["members"] == ["a"]
    assert svc.store.events()[-1]["details"]["reference_topics"] == ["a"]
    with pytest.raises(RevisionConflict):
        svc.edit(group["group_id"], "add", group["revision"], topic="c")
    refreshed = svc.recommendations()["groups"][0]
    assert refreshed["members"] == ["a"]
    undone = svc.edit(group["group_id"], "undo", refreshed["revision"])
    assert undone["members"] == ["a", "b"]
    assert effective_labels(svc.store.events(), svc.registry.manifest_id) == []
    added = svc.edit(group["group_id"], "add", undone["revision"], topic="c")
    assert "c" in added["members"]
    assert "c" not in svc.store.events()[-1]["details"]["reference_topics"]
    saved = svc.edit(group["group_id"], "save", added["revision"], name="Lab")
    assert svc.store.classes()[0]["topics"] == saved["members"]
    edited = svc.edit(group["group_id"], "remove", saved["revision"], topic="c")
    assert svc.store.classes()[0]["topics"] == ["a", "b"]
    restored = svc.edit(group["group_id"], "undo", edited["revision"])
    assert svc.store.classes()[0]["topics"] == restored["members"]


def test_manual_class_persistence_does_not_create_learning_labels():
    svc = service()
    seed(svc)
    svc.manual_class("Sensors", ["a", "b"])
    assert svc.store.events() == []
    assert svc.store.classes()[0]["topics"] == ["a", "b"]

    svc.manual_class("Sensors", ["a", "c"], update=True)
    assert svc.store.events() == []
    assert svc.store.classes()[0]["topics"] == ["a", "c"]


def test_manual_class_remains_non_training_state_across_model_manifest_changes():
    svc = service()
    seed(svc)
    svc.manual_class("Sensors", ["a", "b"])
    svc.registry.model_id = "new-model"
    for topic in ("a", "b", "c"):
        svc.materialize(topic, {"sensor_type": "temperature"})
    svc.manual_class("Sensors", ["a", "c"], update=True)
    assert effective_labels(svc.store.events(), svc.registry.manifest_id) == []


def test_dismissal_does_not_generate_negative_membership_and_can_undo_after_refresh():
    svc = service()
    group = seed(svc)
    svc.edit(group["group_id"], "dismiss", group["revision"])
    group = svc.recommendations()["groups"][0]
    assert group["dismissed"] and group["can_undo"]
    assert effective_labels(svc.store.events(), svc.registry.manifest_id) == []
    assert not svc.edit(group["group_id"], "undo", group["revision"])["dismissed"]


def test_failed_save_rolls_back_group_and_feedback():
    svc = service()
    group = seed(svc)
    svc.manual_class("Existing", ["a"])
    before = svc.store.events()
    with pytest.raises(ValueError):
        svc.edit(group["group_id"], "save", group["revision"], name="Existing")
    assert svc.store.events() == before
    assert svc.store.saved_groups[group["group_id"]]["saved_class"] is None


def training_events(ids, manifest):
    events = []
    for group in range(8):
        for label in (0, 1):
            events.append(dict(event_id=f"event-{group}-{label}", sequence=len(events)+1,
                group_id=f"group-{group}", topic=f"topic-{group}-{label}", action="ADD" if label else "REMOVE",
                label=label, details={"manifest_id": manifest, "reference_topics": [f"reference-{group}"]},
                evidence={key: dict(score=(.95 if label else .05) if i == 0 else (.15 if label else .85),
                                    status="available", coverage=1.) for i, key in enumerate(ids)}))
    return events


def test_weights_learn_a_useful_channel_and_persist_only_in_their_environment():
    a, b = service("lab"), service("factory")
    events = training_events(a.registry.active_ids, a.registry.manifest_id)
    a.store.saved_events = events
    candidate = a.learn()
    assert candidate and candidate["status"] == "learned"
    assert candidate["weights"]["topic_text"] > .25
    assert sum(candidate["weights"].values()) == pytest.approx(1.)
    assert candidate["evaluation"]["candidate_loss"] < candidate["evaluation"]["baseline_loss"]
    assert b.current_model()["status"] == "baseline"
    restarted = service("lab")
    restarted.store = a.store
    assert restarted.current_model()["weights"] == candidate["weights"]
    assert a.learn() is None


def test_sparse_one_sided_or_device_leaking_feedback_cannot_promote():
    registry = ProviderRegistry()
    current = baseline(registry.active_ids, registry.manifest_id)
    events = training_events(registry.active_ids, registry.manifest_id)
    assert train(events[:3], registry.active_ids, registry.manifest_id, current) is None
    assert train([e for e in events if e["label"]], registry.active_ids, registry.manifest_id, current) is None
    for event in events:
        event["details"]["reference_topics"] = ["same-device"]
    assert train(events, registry.active_ids, registry.manifest_id, current) is None


def test_retracted_learning_returns_to_baseline_when_too_few_labels_remain():
    svc = service()
    svc.store.saved_events = training_events(svc.registry.active_ids, svc.registry.manifest_id)
    assert svc.learn()["status"] == "learned"
    original = list(svc.store.saved_events)
    for event in original:
        svc.store.saved_events.append(dict(event_id="undo-"+event["event_id"], sequence=len(svc.store.saved_events)+1,
                                          group_id=event["group_id"], action="UNDO", label=None,
                                          evidence={}, details={"undo_event": event["event_id"]}))
    assert svc.learn()["status"] == "baseline"


def test_aliases_never_contribute_independently():
    svc = service()
    seed(svc)
    svc.identity_store.aliases["b"] = "a"
    response = svc.recommendations()
    assert "b" not in response["available_topics"]
    assert response["groups"][0]["members"] == ["a"]


def test_http_edit_validation_and_manual_class_flow():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from api import classes, recommendations

    svc = service()
    seed(svc)
    app = FastAPI()
    app.state.class_recommendation = SimpleNamespace(adaptive=svc)
    app.include_router(recommendations.router, prefix="/api")
    app.include_router(classes.router, prefix="/api")
    with TestClient(app) as client:
        group = client.get("/api/adaptive-recommendations").json()["groups"][0]
        url = f"/api/adaptive-recommendations/{group['group_id']}/actions"
        assert client.post(url, json={"action": "remove", "revision": 0, "topic": "b"}).status_code == 422
        response = client.post(url, json={"action": "remove", "revision": group["revision"], "topic": "b"})
        assert response.status_code == 200 and response.json()["members"] == ["a"]
        assert client.post(url, json={"action": "remove", "revision": group["revision"], "topic": "a"}).status_code == 409
        created = client.post("/api/classes/", json={"name": "Manual", "topics": ["a", "c"]})
        assert created.status_code == 200, created.text
        assert client.get("/api/classes/").json()["classes"][0]["name"] == "Manual"
        assert client.put("/api/classes/Manual", json={"topics": ["a"]}).status_code == 200
        assert client.delete("/api/classes/Manual").status_code == 200
