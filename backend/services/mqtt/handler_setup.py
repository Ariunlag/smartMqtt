from services.mqtt.client import mqtt_client
from services.mqtt.handlers.influx_handler import InfluxHandler
from services.mqtt.handlers.semantic_handler import SemanticHandler
from services.mqtt.handlers.topic_handler import TopicHandler
from services.mqtt.handlers.ws_handler import Broadcaster
from services.semantic.semantic_processing_service import SemanticProcessingService


def register_mqtt_handlers(
    semantic_service: SemanticProcessingService,
    *,
    client=mqtt_client,
) -> None:
    """Register the stable primary pipeline and its final semantic sidecar."""
    handlers = [
        TopicHandler(),
        InfluxHandler(),
        Broadcaster(),
    ]
    for handler in handlers:
        client.register_handler(handler)
    client.register_handler(SemanticHandler(semantic_service), replace=True)
