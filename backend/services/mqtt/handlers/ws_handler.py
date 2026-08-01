import json

from models.mqtt_message import MQTTMessage
from services.mqtt.base_handler import BaseHandler
from services.socket_manager import ws_manager


class Broadcaster(BaseHandler):
    handler_identity = "broadcaster"

    async def handle_message(self, message: "MQTTMessage") -> None:
        # Broadcast the message to all connected WebSocket clients
        await ws_manager.broadcast(
            {"event_type": "mqtt_message", "data": json.loads(message.json())}
        )
