import logging

from config import config
from services.class_recommendation.domain import PairEmbeddingRecord
from services.socket_manager import ws_manager
from services.store.embedding_store import tagset_store

logger = logging.getLogger(__name__)


class GroupManager:
    """Exploratory tag grouping over the shared recommendation evidence store.

    Tag groups no longer have a separate embedding pipeline. Each tag pair reuses its
    registry-defined `value` vector, preserving the original value-centroid behavior
    while keeping one source of embedding evidence for the whole system.
    """

    def __init__(self, threshold: float = 0.9):
        self.threshold = threshold

    async def update_from_pair_evidence(
        self,
        topic: str,
        records: tuple[PairEmbeddingRecord, ...],
    ) -> None:
        for record in records:
            representation = record.representation
            if representation.identity.source != "tag":
                continue
            value_vector = record.vector_for("value")
            if value_vector is None:
                continue
            tagset_store.find_or_create_set(
                representation.raw_key,
                str(representation.raw_value),
                list(value_vector),
                self.threshold,
                topic,
            )

        valid_sets = [
            {"id": group["id"], "tags": group["tags"]}
            for group in tagset_store.get_all()
            if group["topic_count"] >= 2
        ]
        if valid_sets:
            logger.debug("Broadcasting %s valid tag sets", len(valid_sets))
            await ws_manager.broadcast(
                {"event_type": "group", "data": {"sets": valid_sets}}
            )

    def list_sets(self):
        return [
            {"id": item["id"], "tags": item["tags"]}
            for item in tagset_store.get_all()
            if item["topic_count"] >= 2
        ]

    def get_topics_for_set(self, set_id: str):
        return tagset_store.get_topics(set_id)


# Singleton
groups_manager = GroupManager(threshold=config.GROUP_TAG_THRESH)
