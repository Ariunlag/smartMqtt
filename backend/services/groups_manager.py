# services/group_manager.py
from services.store.embedding_store import tagset_store
from services.socket_manager import ws_manager
import numpy as np
from typing import List


class GroupManager:
    def __init__(self, threshold: float = 0.9):
        self.threshold = threshold

    async def update_for_topic(self, topic: str, tags: dict, embeddings: List[List[float]]):
        updated_sets = []
        for tag, vec in zip(tags.values(), embeddings):
            set_id = tagset_store.find_or_create_set(tag, vec, self.threshold, topic)
            updated_sets.append({"tag": tag, "set": set_id, "topic": topic})

        if updated_sets:
            await ws_manager.broadcast({
                "event_type": "group",
                "data": {
                    "topic": topic,
                    "updated": updated_sets,
                    "sets": tagset_store.get_all()
                }
            })
        return updated_sets


    def list_sets(self):
        return tagset_store.get_all()

    def get_topics_for_set(self, set_id: str):
        return tagset_store.get_topics(set_id)


# Singleton
groups_manager = GroupManager()
