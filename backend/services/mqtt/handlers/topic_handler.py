import asyncio
import logging

from ..base_handler import BaseHandler
from services.store.topic_store import detected_topic_store, ignored_topic_store
from services.embedding_manager import embedding_manager
from services.socket_manager import ws_manager

logger = logging.getLogger(__name__)


class TopicHandler(BaseHandler):
    async def handle_message(self, message):
        topic = message.topic

        # Topic-store lookups hit PostgreSQL (blocking) — run off the loop.
        if await asyncio.to_thread(ignored_topic_store.contains, topic):
            logger.debug("[TopicHandler] Ignored topic: %s", topic)
            return False  # stop further handlers

        if not await asyncio.to_thread(detected_topic_store.contains, topic):
            logger.info("[TopicHandler] New detected topic: %s", topic)

            await embedding_manager.process_new_topic(topic, message.tags)
            await asyncio.to_thread(detected_topic_store.add, topic)

            await ws_manager.broadcast({
                "event_type": "topic",
                "data": {"measurement": topic}
            })

        return True  # continue pipeline
