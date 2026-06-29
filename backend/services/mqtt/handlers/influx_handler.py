from services.mqtt.base_handler import BaseHandler
from services.influx_manager import influx_manager

class InfluxHandler(BaseHandler):
    async def handle_message(self, message):
        return await influx_manager.write_message(message)
