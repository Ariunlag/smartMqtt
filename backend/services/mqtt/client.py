# services/mqtt/client.py
import asyncio
import json
import paho.mqtt.client as mqtt
from config import config
from models.mqtt_message import MQTTMessage

class MQTTClient:
    def __init__(self, broker: str, port: int):
        self.broker = broker
        self.port = port
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self._connected = False
        self.handlers = []
        self.loop: asyncio.AbstractEventLoop | None = None   # store FastAPI loop

    def set_loop(self, loop: asyncio.AbstractEventLoop):
        """Bind the main asyncio loop (called from ServiceManager.startup)."""
        self.loop = loop

    def register_handler(self, handler):
        self.handlers.append(handler)

    def connect(self):
        try:
            self.client.on_connect = self._on_connect
            self.client.on_message = self._on_message
            self.client.connect(self.broker, self.port, 60)
            self.client.loop_start()
            self._connected = True
        except Exception as e:
            print(f"[MQTTClient] Failed to connect: {e}")
            self._connected = False

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        self._connected = (reason_code == 0)
        print(f"[MQTTClient] Connected with broker {self.broker}:{self.port}, rc={reason_code}")

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode())

            data = MQTTMessage(
                topic=msg.topic,
                fields=payload["fields"],
                tags=payload["tags"],
                timestamp=payload["timestamp"]
            )
        except Exception as e:
            print(f"Failed to parse MQTT payload: {e}")
            return

        async def dispatch():
            for handler in self.handlers:
                try:
                    result = handler.handle_message(data)
                    if asyncio.iscoroutine(result):
                        result = await result
                    if result is False:
                        break
                except Exception as e:
                    print(f"[MQTTClient] Handler {handler.__class__.__name__} failed: {e}")

        if self.loop is not None:
            asyncio.run_coroutine_threadsafe(dispatch(), self.loop)
        else:
            print("[MQTTClient] ERROR: No event loop set! Did you forget to call set_loop()?")

    def subscribe(self, topic: str):
        self.client.subscribe(topic)
        print(f"[MQTTClient] Subscribed to {topic}")

    def unsubscribe(self, topic: str):
        self.client.unsubscribe(topic)
        print(f"[MQTTClient] Unsubscribed from {topic}")

    def disconnect(self):
        self.client.loop_stop()
        self.client.disconnect()
        self._connected = False
        print("[MQTTClient] Disconnected")

    def check_health(self) -> bool:
        try:
            return self.client.is_connected()
        except Exception:
            return False


# Singleton instance
mqtt_client = MQTTClient(config.MQTT_BROKER, config.MQTT_PORT)
