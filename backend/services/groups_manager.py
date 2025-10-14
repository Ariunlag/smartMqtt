from services.store.embedding_store import tagset_store
from services.socket_manager import ws_manager
import numpy as np
from typing import List


class GroupManager:
    def __init__(self, threshold: float = 0.9):
        self.threshold = threshold

    async def update_for_topic(self, topic: str, tags: dict, embeddings: List[List[float]]):
        updated_sets = []
        valid_sets = []  # will hold sets that have >= 2 topics

        for tag, vec in zip(tags.values(), embeddings):
            set_id = tagset_store.find_or_create_set(tag, vec, self.threshold, topic)
            topics_in_set = tagset_store.get_topics(set_id)

            # Only include sets that have 2+ topics
            if len(topics_in_set) >= 2:
                updated_sets.append({"tag": tag, "set": set_id, "topic": topic})
                valid_sets.append({
                    "set_id": set_id,
                    "topics": topics_in_set
                })

        # Broadcast only if at least one set qualifies
        if updated_sets:
            await ws_manager.broadcast({
                "event_type": "group",
                "data": {
                    "topic": topic,
                    "updated": updated_sets,
                    "sets": valid_sets
                }
            })

        return updated_sets

    def list_sets(self):
        return tagset_store.get_all()

    def get_topics_for_set(self, set_id: str):
        return tagset_store.get_topics(set_id)


# Singleton
groups_manager = GroupManager()
