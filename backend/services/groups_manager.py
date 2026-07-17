import logging
from services.store.embedding_store import tagset_store
from services.socket_manager import ws_manager
from typing import List
from config import config


logger = logging.getLogger(__name__)


class GroupManager:
    def __init__(self, threshold: float = 0.9):
        self.threshold = threshold

    async def update_for_topic(
        self,
        topic: str,
        tag_items: list[tuple[str, str]],
        embeddings: List[List[float]],
    ):
        """
        Called whenever a new topic's tags are embedded.
        Creates/updates tag sets and broadcasts all sets that have >= 2 topics.
        """
        # --- step 1: update or create sets ---
        for (tag_key, tag_value), vec in zip(tag_items, embeddings):
            tagset_store.find_or_create_set(
                tag_key,
                tag_value,
                vec,
                self.threshold,
                topic,
            )

        # --- step 2: collect all valid sets for broadcast ---
        valid_sets = []
        for group in tagset_store.get_all():
            if group["topic_count"] >= 2:
                valid_sets.append({"id": group["id"], "tags": group["tags"]})

        # --- step 3: broadcast full valid state once ---
        if valid_sets:
            logger.debug("Broadcasting %s valid tag sets", len(valid_sets))
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
            for s in tagset_store.get_all()
            if s["topic_count"] >= 2
        ]
        return valid_sets


    def get_topics_for_set(self, set_id: str):
        return tagset_store.get_topics(set_id)


# Singleton
groups_manager = GroupManager(threshold=config.GROUP_TAG_THRESH)
