import asyncio
import logging

from config import config
from services.duplicate.canonicalization_service import DuplicateCanonicalizationService
from services.duplicate.duplicate_service import duplicate_service
from services.socket_manager import ws_manager
from services.store.canonical_identity_store import canonical_identity_store
from services.store.embedding_store import topic_embedding_store
from services.store.relation_store import dupe_store
from services.topic_manager import topic_manager

logger = logging.getLogger(__name__)


class DupeManager:
    """Detects, stores, and resolves potential duplicate topics."""

    def __init__(
        self,
        store=dupe_store,
        canonicalization_service=None,
    ):
        self.store = store
        self.canonicalization_service = canonicalization_service or (
            DuplicateCanonicalizationService(canonical_identity_store, store)
        )
        self.id_thresh = config.ID_THRESH
        self.delay = config.DUPE_CHECK_DELAY

    async def check_new_topic(self, topic: str, embedding: list[float]):
        """Schedule a delayed check when a new topic is embedded."""
        if hasattr(embedding, "tolist"):
            embedding = embedding.tolist()
        asyncio.create_task(self._delayed_check(topic, embedding))

    async def _delayed_check(self, topic: str, embedding: list[float]):
        for _ in range(3):  # check up to 3 times (every 2 min)
            await asyncio.sleep(self.delay)

            candidates = topic_embedding_store.candidates_for(
                topic,
                embedding,
                limit=10,
            )
            for rec in candidates:
                other = rec["topic"]
                if other == topic:
                    continue

                score = await duplicate_service.hybrid_score(
                    topic, embedding, other, rec["embedding"]
                )
                if score >= self.id_thresh:
                    record, created = self.create_candidate(topic, other, score)
                    if created and record["status"] == "PENDING":
                        await ws_manager.broadcast(
                            {"event_type": "duplicate", "data": record}
                        )
                        return
                    if record["status"] == "PENDING":
                        return
                    continue

        logger.debug("No duplicates found for %s after retries.", topic)

    def add_candidate(self, topic_a: str, topic_b: str, score: float) -> dict:
        """Add a duplicate candidate if not already stored."""
        return self.create_candidate(topic_a, topic_b, score)[0]

    def create_candidate(
        self, topic_a: str, topic_b: str, score: float
    ) -> tuple[dict, bool]:
        """Atomically create one pending event without reopening terminal pairs."""
        return self.store.create_pending(topic_a, topic_b, score)

    def confirm_duplicate(
        self,
        topic_a: str,
        topic_b: str,
        target: str | None = None,
        recommendation_application=None,
    ) -> dict | None:
        """Commit canonical identity, reconcile state, then unsubscribe the alias."""
        target = target or topic_b
        result = self.canonicalization_service.confirm(
            topic_a,
            topic_b,
            target,
            recommendation_application=recommendation_application,
        )
        if result is None:
            return None
        topic_manager.unsubscribe(target)
        return result.record

    def keep_both(self, topic_a: str, topic_b: str) -> dict | None:
        """Mark a pair as not duplicates and keep both topics."""
        rec = self.find_pair(topic_a, topic_b)
        if not rec:
            return None
        if rec["status"] != "PENDING":
            return rec
        return self.store.update_status(topic_a, topic_b, "NOT_DUPLICATE")

    def find_pair(self, topic_a: str, topic_b: str) -> dict | None:
        """Find a stored duplicate pair, if it exists."""
        return self.store.get_pair(topic_a, topic_b)

    def list_pending(self) -> list[dict]:
        """Return all pending duplicate pairs."""
        return [r for r in self.store.get_all() if r["status"] == "PENDING"]


# Singleton instance
dupe_manager = DupeManager()
