from services.store.embedding_store import tagset_store
from services.socket_manager import ws_manager
import numpy as np
from typing import List


class GroupManager:
    def __init__(self, threshold: float = 0.9):
        self.threshold = threshold

    async def update_for_topic(self, topic: str, tags: dict, embeddings: List[List[float]]):
        """
        Called whenever a new topic's tags are embedded.
        Creates/updates tag sets and broadcasts all sets that have >= 2 topics.
        """
        # --- step 1: update or create sets ---
        for tag, vec in zip(tags.values(), embeddings):
            tagset_store.find_or_create_set(tag, vec, self.threshold, topic)

        # --- step 2: collect all valid sets for broadcast ---
        valid_sets = []
        for s in tagset_store._data:
            topics = s.get("topics", [])
            if len(topics) >= 2:
                valid_sets.append({"id": s["id"], "tags": s["tags"]})

        # --- step 3: broadcast full valid state once ---
        if valid_sets:
            print(f"[DEBUG] Broadcasting {len(valid_sets)} valid tag sets")
            await ws_manager.broadcast({
                "event_type": "group",
                "data": {"sets": valid_sets}
            })


    def list_sets(self):
        """
        Return all tag sets that have at least 2 topics.
        Each entry includes only id and tags (for UI and API).
        """
        valid_sets = [
            {"id": s["id"], "tags": s["tags"]}
            for s in tagset_store._data
            if len(s.get("topics", [])) >= 2
        ]
        return valid_sets


    def get_topics_for_set(self, set_id: str):
        return tagset_store.get_topics(set_id)


# Singleton
groups_manager = GroupManager()
