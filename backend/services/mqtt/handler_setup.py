from services.mqtt.client import mqtt_client
from services.mqtt.handlers.topic_handler import TopicHandler
from services.mqtt.handlers.influx_handler import InfluxHandler
from services.mqtt.handlers.ws_handler import Broadcaster

def register_mqtt_handlers():
    handlers = [
        TopicHandler(),
        InfluxHandler(),
        Broadcaster(),
    ]
    for handler in handlers:
        mqtt_client.register_handler(handler)
