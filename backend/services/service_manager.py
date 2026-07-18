import asyncio
import logging

from config import config
from services.mqtt.handler_setup import register_mqtt_handlers
from services.mqtt.client import mqtt_client
from services.influx.client import influx_client
from services.database.postgres import postgres_client
from services.database.qdrant import qdrant_client
from services.dependency_monitor import DependencyMonitor
from services.topic_manager import topic_manager

logger = logging.getLogger(__name__)


class ServiceManager:
    def __init__(self):
        self.services = [
            postgres_client,
            qdrant_client,
            mqtt_client,
            influx_client,
        ]
        self.monitor = DependencyMonitor(
            self.services,
            timeout=config.HEALTH_CHECK_TIMEOUT,
            base_delay=config.RECOVERY_BASE_DELAY,
            max_delay=config.RECOVERY_MAX_DELAY,
            on_recover=self._on_recover,
        )

    async def _on_recover(self, name: str) -> None:
        # When MQTT (re)connects, restore subscriptions. Runs off the event loop
        # because resubscribe touches the (blocking) DB + broker client.
        if name == mqtt_client.__class__.__name__:
            logger.info("MQTT connected — restoring subscriptions")
            await asyncio.to_thread(topic_manager.resubscribe_all)

    async def startup(self):
        """Non-blocking startup: liveness is up immediately; dependencies are
        connected in the background so the app does not crash-loop when a
        dependency is temporarily unavailable."""
        loop = asyncio.get_running_loop()
        logger.info("[Startup] Using loop %s", id(loop))

        register_mqtt_handlers()
        for service in self.services:
            if hasattr(service, "set_loop"):
                service.set_loop(loop)

        # Start ingestion workers before MQTT connects so the queue is ready
        # to receive messages the moment the broker delivers them.
        mqtt_client.start_ingestion()

        await self.monitor.start()
        logger.info("[Startup] Dependency monitor started")

    async def shutdown(self):
        await self.monitor.stop()
        await mqtt_client.stop_ingestion()
        for service in self.services:
            if hasattr(service, "disconnect"):
                try:
                    service.disconnect()
                except Exception:
                    logger.exception(
                        "disconnect failed: %s", service.__class__.__name__
                    )
        logger.info("[Shutdown] All services disconnected")

    async def check_all(self) -> dict[str, dict]:
        return await self.monitor.snapshot()

    def is_ready(self, snapshot: dict[str, dict]) -> bool:
        return self.monitor.is_ready(snapshot)


service_manager = ServiceManager()
