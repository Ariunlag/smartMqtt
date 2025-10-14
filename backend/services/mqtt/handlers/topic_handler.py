from ..base_handler import BaseHandler
from services.store.topic_store import detected_topic_store, ignored_topic_store
from services.embedding_manager import embedding_manager
from services.socket_manager import ws_manager

class TopicHandler(BaseHandler):
    async def handle_message(self, message):       
        topic = message.topic

        if topic in ignored_topic_store.get_all():
            print(f"[TopicHandler] Ignored topic: {topic}")
            return False   # stop further handlers

        if topic not in detected_topic_store.get_all():
            detected_topic_store.add(topic)
            print(f"[TopicHandler] New detected topic: {topic}")

            await embedding_manager.process_new_topic(topic, message.tags)

            await ws_manager.broadcast({
                "event_type": "topic",
                "data": {"measurement": topic}
            })

        return True  # continue pipeline
