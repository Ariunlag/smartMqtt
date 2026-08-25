import asyncio
import logging

from config import config
from services.database.postgres import postgres_client
from services.database.qdrant import qdrant_client
from services.dependency_monitor import DependencyMonitor
from services.influx.client import influx_client
from services.mqtt.client import mqtt_client
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
        self._class_recommendation_application = None

    async def _on_recover(self, name: str) -> None:
        # When MQTT (re)connects, restore subscriptions. Runs off the event loop
        # because resubscribe touches the (blocking) DB + broker client.
        if name == mqtt_client.__class__.__name__:
            logger.info("MQTT connected — restoring subscriptions")
            await asyncio.to_thread(topic_manager.resubscribe_all)

    async def startup(self, class_recommendation_application):
        """Non-blocking startup: liveness is up immediately; dependencies are
        connected in the background so the app does not crash-loop when a
        dependency is temporarily unavailable."""
        loop = asyncio.get_running_loop()
        logger.info("[Startup] Using loop %s", id(loop))

        # Import lazily so importing the FastAPI app does not construct the
        # configured sentence-transformer embedding model.
        from services.mqtt.handler_setup import register_mqtt_handlers

        self._class_recommendation_application = class_recommendation_application
        await class_recommendation_application.processing_service.start()
        register_mqtt_handlers(
            class_recommendation_application.processing_service,
            identity_store=class_recommendation_application.identity_store,
        )
        for service in self.services:
            if hasattr(service, "set_loop"):
                service.set_loop(loop)

        # Start ingestion workers before MQTT connects so the queue is ready
        # to receive messages the moment the broker delivers them.
        mqtt_client.start_ingestion()

        await self.monitor.start()
        logger.info("[Startup] Dependency monitor started")

    async def shutdown(self):
        await mqtt_client.stop_ingestion()
        if self._class_recommendation_application is not None:
            await self._class_recommendation_application.processing_service.stop()
        await self.monitor.stop()
        for service in self.services:
            if hasattr(service, "disconnect"):
                try:
                    service.disconnect()
                except Exception:
                    logger.exception(
                        "disconnect failed: %s", service.__class__.__name__
                    )
        logger.info("[Shutdown] All services disconnected")
        self._class_recommendation_application = None

    async def check_all(self) -> dict[str, dict]:
        return await self.monitor.snapshot()

    def is_ready(self, snapshot: dict[str, dict]) -> bool:
        return self.monitor.is_ready(snapshot)


service_manager = ServiceManager()
