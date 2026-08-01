# services/mqtt/client.py
import asyncio
import json
import logging

import paho.mqtt.client as mqtt
from config import config
from models.mqtt_message import MQTTMessage
from services.mqtt.ingestion import IngestionQueue

logger = logging.getLogger(__name__)


class MQTTClient:
    def __init__(self, broker: str, port: int):
        self.broker = broker
        self.port = port
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self._connected = False
        self.handlers = []
        self.loop: asyncio.AbstractEventLoop | None = None  # store FastAPI loop
        # Bounded ingestion queue feeding the existing handler pipeline.
        self.ingestion = IngestionQueue(
            self._dispatch_pipeline,
            maxsize=config.INGEST_QUEUE_MAXSIZE,
            workers=config.INGEST_WORKERS,
            full_policy=config.INGEST_QUEUE_FULL_POLICY,
            max_retries=config.INGEST_MAX_RETRIES,
            retry_delay=config.INGEST_RETRY_DELAY,
            metrics_interval=config.INGEST_METRICS_INTERVAL,
        )

    def set_loop(self, loop: asyncio.AbstractEventLoop):
        """Bind the main asyncio loop (called from ServiceManager.startup)."""
        self.loop = loop

    def register_handler(self, handler, *, replace: bool = False):
        identity = getattr(handler, "handler_identity", None)
        if identity is not None:
            for index, existing in enumerate(self.handlers):
                if getattr(existing, "handler_identity", None) == identity:
                    if replace:
                        self.handlers[index] = handler
                    return
        self.handlers.append(handler)

    def start_ingestion(self):
        """Start the ingestion workers. Must run on the event loop."""
        if self.loop is None:
            raise RuntimeError("event loop not set; call set_loop() first")
        self.ingestion.start(self.loop)

    async def stop_ingestion(self):
        await self.ingestion.stop()

    def connect(self):
        try:
            self.client.on_connect = self._on_connect
            self.client.on_message = self._on_message
            self.client.connect(self.broker, self.port, 60)
            self.client.loop_start()
            self._connected = True
        except Exception as e:
            logger.warning("[MQTTClient] Failed to connect: %s", e)
            self._connected = False

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        self._connected = reason_code == 0
        logger.info(
            "[MQTTClient] Connected to %s:%s rc=%s", self.broker, self.port, reason_code
        )

    def _on_message(self, client, userdata, msg):
        """Paho network-thread callback. Kept short: parse + hand off to the
        bounded ingestion queue. No unbounded task creation here."""
        try:
            payload = json.loads(msg.payload.decode())
            data = MQTTMessage(
                topic=msg.topic,
                fields=payload["fields"],
                tags=payload["tags"],
                timestamp=payload["timestamp"],
            )
        except Exception as e:
            logger.warning(
                "[MQTTClient] Failed to parse payload on %s: %s", msg.topic, e
            )
            return

        self.ingestion.submit_threadsafe(data)

    async def _dispatch_pipeline(self, message: MQTTMessage) -> None:
        """Run the existing handler pipeline for one message (on a worker).

        Errors are not swallowed — they propagate to the ingestion layer, which
        records the failure and applies the configured retry policy.
        """
        for handler in self.handlers:
            result = handler.handle_message(message)
            if asyncio.iscoroutine(result):
                result = await result
            if result is False:
                break

    def subscribe(self, topic: str):
        self.client.subscribe(topic)
        logger.info("[MQTTClient] Subscribed to %s", topic)

    def unsubscribe(self, topic: str):
        self.client.unsubscribe(topic)
        logger.info("[MQTTClient] Unsubscribed from %s", topic)

    def disconnect(self):
        self.client.loop_stop()
        self.client.disconnect()
        self._connected = False
        logger.info("[MQTTClient] Disconnected")

    def check_health(self) -> bool:
        try:
            return self.client.is_connected()
        except Exception:
            return False


# Singleton instance
mqtt_client = MQTTClient(config.MQTT_BROKER, config.MQTT_PORT)
