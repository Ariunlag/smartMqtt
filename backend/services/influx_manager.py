from services.influx.client import influx_client
from models.mqtt_message import MQTTMessage

""" Manages InfluxDB write operations. """

class InfluxManager:
    def __init__(self):
        self.client = influx_client  # reuse singleton client

    async def write_message(self, message: MQTTMessage) -> bool:
        """Write MQTTMessage to Influx via client."""
        try:
            self.client.write_point(
                measurement=message.topic,
                tags=message.tags,
                fields=message.fields,
                timestamp=message.timestamp
            )
            return True
        except Exception as e:
            print(f"[InfluxManager] Failed to write message: {e}")
            return False


# Singleton
influx_manager = InfluxManager()
