import asyncio
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from main import create_app
from models.mqtt_message import MQTTMessage
from services.embedding.base_model import BaseEmbeddingModel
from services.mqtt.client import MQTTClient
from services.mqtt.handler_setup import register_mqtt_handlers
from services.mqtt.handlers.influx_handler import InfluxHandler
from services.mqtt.handlers.semantic_handler import SemanticHandler
from services.mqtt.handlers.topic_handler import TopicHandler
from services.mqtt.handlers.ws_handler import Broadcaster
from services.semantic import (
    SemanticClassDecisionConfig,
    SemanticClassDecisionPolicy,
    build_semantic_application,
)
from services.service_manager import ServiceManager


class ConstantEmbeddingModel(BaseEmbeddingModel):
    def encode(self, texts):
        return [(1.0, 0.0) for _ in texts]


class FailFirstEmbeddingModel(BaseEmbeddingModel):
    def __init__(self):
        self.calls = 0

    def encode(self, texts):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("semantic embedding failed")
        return [(1.0, 0.0) for _ in texts]


class RecordingPrimaryHandler:
    def __init__(self, name, calls):
        self.name = name
        self.calls = calls

    async def handle_message(self, message):
        self.calls.append((self.name, message.topic))
        return True


def _policy():
    return SemanticClassDecisionPolicy(SemanticClassDecisionConfig(1, 0.8, 0.0, 0.2))


def _application(model=None):
    return build_semantic_application(
        embedding_model=model or ConstantEmbeddingModel(),
        known_classes=(),
        decision_policy=_policy(),
    )


def _message(topic):
    return MQTTMessage(
        topic=topic,
        tags={"site": "lab"},
        fields={"reading": 1.0},
        timestamp="2024-01-01T00:00:00Z",
    )


async def _wait_for(predicate, timeout=2.0):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.005)


def test_handler_setup_preserves_primary_order_adds_semantic_last_and_is_idempotent():
    client = MQTTClient("unused", 1883)
    application = _application()

    register_mqtt_handlers(application.processing_service, client=client)
    register_mqtt_handlers(application.processing_service, client=client)

    assert tuple(type(handler) for handler in client.handlers) == (
        TopicHandler,
        InfluxHandler,
        Broadcaster,
        SemanticHandler,
    )
    assert tuple(handler.handler_identity for handler in client.handlers) == (
        "topic",
        "influx",
        "broadcaster",
        "semantic",
    )
    assert client.handlers[-1].processing_service is application.processing_service


async def test_dispatch_sidecar_commits_semantics_without_repeating_primary_handlers():
    client = MQTTClient("unused", 1883)
    application = _application()
    calls = []
    client.handlers = [
        RecordingPrimaryHandler("topic", calls),
        RecordingPrimaryHandler("influx", calls),
        RecordingPrimaryHandler("broadcaster", calls),
        SemanticHandler(application.processing_service),
    ]
    await application.processing_service.start()

    await client._dispatch_pipeline(_message("sensor/success"))
    await _wait_for(
        lambda: application.processing_service.status().processed_count == 1
    )
    await application.processing_service.stop()

    assert calls == [
        ("topic", "sensor/success"),
        ("influx", "sensor/success"),
        ("broadcaster", "sensor/success"),
    ]
    assert application.processing_runtime.state_store.get("sensor/success") is not None
    assert application.unknown_pool.get("sensor/success") is not None


async def test_semantic_failure_isolated_from_primary_pipeline_and_worker_continues():
    client = MQTTClient("unused", 1883)
    application = _application(FailFirstEmbeddingModel())
    calls = []
    client.handlers = [
        RecordingPrimaryHandler("topic", calls),
        RecordingPrimaryHandler("influx", calls),
        RecordingPrimaryHandler("broadcaster", calls),
        SemanticHandler(application.processing_service),
    ]
    await application.processing_service.start()

    await client._dispatch_pipeline(_message("sensor/fails"))
    await client._dispatch_pipeline(_message("sensor/recovers"))
    await _wait_for(
        lambda: (
            application.processing_service.status().failed_count
            + application.processing_service.status().processed_count
            == 2
        )
    )
    status = application.processing_service.status()
    await application.processing_service.stop()

    assert calls == [
        ("topic", "sensor/fails"),
        ("influx", "sensor/fails"),
        ("broadcaster", "sensor/fails"),
        ("topic", "sensor/recovers"),
        ("influx", "sensor/recovers"),
        ("broadcaster", "sensor/recovers"),
    ]
    assert status.failed_count == 1
    assert status.processed_count == 1
    assert status.last_error_topic == "sensor/fails"
    assert status.last_processed_topic == "sensor/recovers"
    assert application.processing_runtime.state_store.get("sensor/fails") is None
    assert application.processing_runtime.state_store.get("sensor/recovers") is not None


async def test_service_manager_starts_and_stops_sidecar_in_required_order(monkeypatch):
    events = []

    class ProcessingService:
        async def start(self):
            events.append("semantic-start")

        async def stop(self):
            events.append("semantic-stop")

    class Monitor:
        async def start(self):
            events.append("monitor-start")

        async def stop(self):
            events.append("monitor-stop")

    class Mqtt:
        def set_loop(self, _loop):
            events.append("mqtt-loop")

        def start_ingestion(self):
            events.append("mqtt-start")

        async def stop_ingestion(self):
            events.append("mqtt-stop")

        def disconnect(self):
            events.append("mqtt-disconnect")

    semantic_application = SimpleNamespace(processing_service=ProcessingService())
    mqtt = Mqtt()
    manager = ServiceManager()
    manager.services = [mqtt]
    manager.monitor = Monitor()

    import services.service_manager as service_manager_module
    from services.mqtt import handler_setup

    monkeypatch.setattr(service_manager_module, "mqtt_client", mqtt)
    monkeypatch.setattr(
        handler_setup,
        "register_mqtt_handlers",
        lambda service: events.append(("handlers", service)),
    )

    await manager.startup(semantic_application)
    await manager.shutdown()

    assert events == [
        "semantic-start",
        ("handlers", semantic_application.processing_service),
        "mqtt-loop",
        "mqtt-start",
        "monitor-start",
        "mqtt-stop",
        "semantic-stop",
        "monitor-stop",
        "mqtt-disconnect",
    ]


def test_processing_status_endpoint_uses_application_state_without_sensitive_data():
    application = _application()
    app = create_app(semantic_application=application, manage_services=False)

    with TestClient(app) as client:
        response = client.get("/api/semantic-review/processing-status")

    assert response.status_code == 200
    assert response.json() == {
        "running": False,
        "enabled": True,
        "queue_size": 0,
        "queue_capacity": 256,
        "submitted_count": 0,
        "processed_count": 0,
        "failed_count": 0,
        "dropped_count": 0,
        "last_processed_topic": None,
        "last_error_topic": None,
        "last_error_message": None,
    }
    assert "embedding" not in response.text.lower()
    assert "payload" not in response.text.lower()


def test_importing_main_does_not_import_or_construct_embedding_manager():
    backend = Path(__file__).resolve().parents[1]
    check = (
        "import sys; import main; "
        "assert 'services.embedding_manager' not in sys.modules"
    )

    result = subprocess.run(
        [sys.executable, "-c", check],
        cwd=backend,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_frontend_and_graph_sources_are_untouched_by_sidecar_work():
    root = Path(__file__).resolve().parents[2]
    app_source = (root / "frontend/src/App.tsx").read_text(encoding="utf-8")

    for component in (
        "MqttManager",
        "DuplicateManager",
        "ClassBuilder",
        "SavedClasses",
        "GroupManager",
        "SemanticReviewManager",
    ):
        assert component in app_source
    duplicate_source = (
        root / "frontend/src/components/duplicates/DuplicateManager.tsx"
    ).read_text(encoding="utf-8")
    assert "DupeGraph" in duplicate_source
