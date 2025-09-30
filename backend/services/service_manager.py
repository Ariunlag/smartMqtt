import asyncio
from services.mqtt.handler_setup import register_mqtt_handlers
from services.mqtt.client import mqtt_client
from services.influx.client import influx_client
from services.topic_manager import topic_manager

class ServiceManager:
    def __init__(self):
        self.services = [mqtt_client, influx_client]

    async def startup(self):
        loop = asyncio.get_running_loop()
        print(f"[Startup] Using loop {id(loop)}")

        register_mqtt_handlers()
        # connect all services
        for service in self.services:
            if hasattr(service, "set_loop"):
                service.set_loop(loop)
            if hasattr(service, "connect"):
                service.connect()

        await asyncio.sleep(0.5)
        topic_manager.resubscribe_all()

        # check health
        for service in self.services:
            if hasattr(service, "check_health") and not service.check_health():
                raise RuntimeError(f"[Startup] {service.__class__.__name__} failed health check!")

        print("[Startup] All services healthy ")

    async def shutdown(self):
        for service in self.services:
            if hasattr(service, "disconnect"):
                service.disconnect()
        print("[Shutdown] All services disconnected")
        

    

service_manager = ServiceManager()
