import asyncio
import logging

from services.socket_manager import ws_manager
from services.store.topic_store import detected_topic_store, ignored_topic_store

from ..base_handler import BaseHandler

logger = logging.getLogger(__name__)


class TopicHandler(BaseHandler):
    handler_identity = "topic"

    async def handle_message(self, message):
        topic = message.topic

        # Topic-store lookups hit PostgreSQL (blocking) — run off the loop.
        if await asyncio.to_thread(ignored_topic_store.contains, topic):
            logger.debug("[TopicHandler] Ignored topic: %s", topic)
            return False  # stop further handlers

        if not await asyncio.to_thread(detected_topic_store.contains, topic):
            logger.info("[TopicHandler] New detected topic: %s", topic)

            # Construct the configured model only when the existing new-topic
            # pipeline first needs it.
            from services.embedding_manager import embedding_manager

            await embedding_manager.process_new_topic(topic, message.tags)
            await asyncio.to_thread(detected_topic_store.add, topic)

            await ws_manager.broadcast(
                {"event_type": "topic", "data": {"measurement": topic}}
            )

        return True  # continue pipeline
