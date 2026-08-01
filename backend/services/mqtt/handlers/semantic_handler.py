"""Non-blocking MQTT handoff to the semantic processing sidecar."""

from models.mqtt_message import MQTTMessage
from services.mqtt.base_handler import BaseHandler
from services.semantic.semantic_processing_service import SemanticProcessingService


class SemanticHandler(BaseHandler):
    """Submit messages without waiting for profiling or embedding work."""

    handler_identity = "semantic"

    def __init__(self, processing_service: SemanticProcessingService) -> None:
        self.processing_service = processing_service

    def handle_message(self, message: MQTTMessage) -> bool:
        self.processing_service.submit(message)
        return True
