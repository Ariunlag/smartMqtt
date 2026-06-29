import asyncio
from services.mqtt.handler_setup import register_mqtt_handlers
from services.mqtt.client import mqtt_client
from services.influx.client import influx_client
from services.database.postgres import postgres_client
from services.database.qdrant import qdrant_client
from services.topic_manager import topic_manager

class ServiceManager:
    def __init__(self):
        self.services = [
            postgres_client,
            qdrant_client,
            mqtt_client,
            influx_client,
        ]

    async def startup(self):
        loop = asyncio.get_running_loop()
        print(f"[Startup] Using loop {id(loop)}")

        register_mqtt_handlers()
        timeout_seconds = 30
        start_time = loop.time()

        for service in self.services:
            if hasattr(service, "set_loop"):
                service.set_loop(loop)

        while True:
            all_healthy = True
            for service in self.services:
                healthy = (
                    service.check_health()
                    if hasattr(service, "check_health")
                    else False
                )
                if not healthy and hasattr(service, "connect"):
                    service.connect()
                    healthy = (
                        service.check_health()
                        if hasattr(service, "check_health")
                        else True
                    )
                if not healthy:
                    all_healthy = False

            if all_healthy:
                break

            if loop.time() - start_time > timeout_seconds:
                raise RuntimeError("[Startup] One or more required services did not become healthy in time")

            await asyncio.sleep(2)

        await asyncio.sleep(0.5)
        topic_manager.resubscribe_all()
        print("[Startup] All services healthy ")

    async def shutdown(self):
        for service in self.services:
            if hasattr(service, "disconnect"):
                service.disconnect()
        print("[Shutdown] All services disconnected")
        

    

service_manager = ServiceManager()
