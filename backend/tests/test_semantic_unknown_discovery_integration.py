import asyncio

from fastapi.testclient import TestClient
from main import create_app
from models.mqtt_message import MQTTMessage
from services.embedding.base_model import BaseEmbeddingModel
from services.mqtt.client import MQTTClient
from services.mqtt.handlers.semantic_handler import SemanticHandler
from services.semantic import (
    CandidateIdentity,
    HDBSCANDiscoveryConfig,
    SemanticClassDecisionConfig,
    SemanticClassDecisionPolicy,
    SemanticClassDecisionState,
    SemanticDiscoveryConfig,
    build_semantic_application,
)


class ConstantEmbeddingModel(BaseEmbeddingModel):
    def encode(self, texts):
        return [(1.0, 0.0) for _ in texts]


class RecordingPrimaryHandler:
    def __init__(self, name, calls):
        self.name = name
        self.calls = calls

    async def handle_message(self, message):
        self.calls.append((self.name, message.topic))
        return True


def _message(topic):
    return MQTTMessage(
        topic=topic,
        tags={"site": "lab"},
        fields={"reading": 1.0},
        timestamp="2024-01-01T00:00:00Z",
    )


async def _wait_for(predicate, timeout=5.0):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.01)


async def test_mqtt_unknowns_publish_review_then_live_classifies_without_primary_replay():
    application = build_semantic_application(
        embedding_model=ConstantEmbeddingModel(),
        known_classes=(),
        decision_policy=SemanticClassDecisionPolicy(
            SemanticClassDecisionConfig(1, 0.8, 0.0, 0.2)
        ),
        hdbscan_config=HDBSCANDiscoveryConfig(
            min_cluster_size=2,
            min_samples=1,
            allow_single_cluster=True,
        ),
        discovery_config=SemanticDiscoveryConfig(debounce_seconds=0.01),
    )
    mqtt = MQTTClient("unused", 1883)
    primary_calls = []
    mqtt.handlers = [
        RecordingPrimaryHandler("topic", primary_calls),
        RecordingPrimaryHandler("influx", primary_calls),
        RecordingPrimaryHandler("broadcaster", primary_calls),
        SemanticHandler(application.processing_service),
    ]
    await application.discovery_service.start()
    await application.processing_service.start()

    for topic in ("related/A", "related/B", "related/C"):
        await mqtt._dispatch_pipeline(_message(topic))
    await _wait_for(
        lambda: application.processing_service.status().processed_count == 3
    )
    await _wait_for(lambda: len(application.review_runtime.list_candidates()) == 6)

    app = create_app(semantic_application=application, manage_services=False)
    with TestClient(app) as client:
        candidates_response = client.get("/api/semantic-review/candidates")
        candidate = next(
            item
            for item in candidates_response.json()["candidates"]
            if item["representation_name"] == "key_value"
        )
        review_response = client.post(
            "/api/semantic-review/reviews",
            json={
                "identity": {
                    "representation_name": candidate["representation_name"],
                    "member_topics": candidate["member_topics"],
                },
                "class_id": "related-sensor",
                "semantic_class_name": "Related Sensor",
                "kept_topics": candidate["member_topics"],
                "removed_topics": [],
                "added_topics": [],
            },
        )

    assert candidates_response.status_code == 200
    assert review_response.status_code == 200
    reviewed_identity = CandidateIdentity(
        candidate["representation_name"], tuple(candidate["member_topics"])
    )
    assert reviewed_identity not in tuple(
        item.identity for item in application.review_runtime.list_candidates()
    )
    known_class = application.known_class_registry.get("related-sensor")
    assert known_class is not None
    assert len(known_class.centroids.as_dict()) == 6

    published_before = application.discovery_service.status().published_count
    application.discovery_service.request()
    await _wait_for(
        lambda: (
            application.discovery_service.status().published_count
            == published_before + 1
        )
    )
    assert reviewed_identity not in tuple(
        item.identity for item in application.review_runtime.list_candidates()
    )

    await mqtt._dispatch_pipeline(_message("related/D"))
    await _wait_for(
        lambda: application.processing_service.status().processed_count == 4
    )
    state = application.processing_runtime.state_store.get("related/D")

    await application.processing_service.stop()
    await application.discovery_service.stop()

    assert state.decision.state is SemanticClassDecisionState.KNOWN
    assert state.decision.candidate.class_id == "related-sensor"
    assert primary_calls == [
        (handler, topic)
        for topic in ("related/A", "related/B", "related/C", "related/D")
        for handler in ("topic", "influx", "broadcaster")
    ]
