"""Non-blocking MQTT handoff to pair-level class recommendation processing."""

from services.mqtt.base_handler import BaseHandler


class ClassRecommendationHandler(BaseHandler):
    handler_identity = "class-recommendation"

    def __init__(self, processing_service) -> None:
        self.processing_service = processing_service

    def handle_message(self, message) -> bool:
        self.processing_service.submit(message)
        return True
