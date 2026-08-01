from services.influx_manager import influx_manager
from services.mqtt.base_handler import BaseHandler


class InfluxHandler(BaseHandler):
    handler_identity = "influx"

    async def handle_message(self, message):
        return await influx_manager.write_message(message)
