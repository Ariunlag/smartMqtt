from services.mqtt.client import mqtt_client
from services.mqtt.handlers.canonical_identity_handler import CanonicalIdentityHandler
from services.mqtt.handlers.class_recommendation_handler import (
    ClassRecommendationHandler,
)
from services.mqtt.handlers.influx_handler import InfluxHandler
from services.mqtt.handlers.topic_handler import TopicHandler
from services.mqtt.handlers.ws_handler import Broadcaster


def register_mqtt_handlers(
    recommendation_service,
    *,
    client=mqtt_client,
    identity_store=None,
) -> None:
    """Register the stable primary pipeline and final recommendation sidecar."""
    handlers = [
        CanonicalIdentityHandler(identity_store)
        if identity_store is not None
        else CanonicalIdentityHandler(),
        TopicHandler(),
        InfluxHandler(),
        Broadcaster(),
    ]
    for handler in handlers:
        client.register_handler(handler)
    client.register_handler(
        ClassRecommendationHandler(recommendation_service), replace=True
    )
