import asyncio
import logging

from services.influx.client import influx_client
from models.mqtt_message import MQTTMessage

logger = logging.getLogger(__name__)

""" Manages InfluxDB write operations. """

class InfluxManager:
    def __init__(self):
        self.client = influx_client  # reuse singleton client

    async def write_message(self, message: MQTTMessage) -> bool:
        """Write MQTTMessage to Influx. The client write is blocking, so it is
        run off the event loop."""
        try:
            await asyncio.to_thread(
                self.client.write_point,
                message.topic,
                message.tags,
                message.fields,
                message.timestamp,
            )
            return True
        except Exception as e:
            logger.warning("[InfluxManager] Failed to write message: %s", e)
            return False


# Singleton
influx_manager = InfluxManager()
