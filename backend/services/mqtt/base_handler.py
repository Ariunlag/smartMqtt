from models.mqtt_message import MQTTMessage


class BaseHandler:
    def handle_message(self, message: "MQTTMessage"):
        raise NotImplementedError