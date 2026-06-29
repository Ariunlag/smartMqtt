import asyncio
from typing import List, Optional
from config import config
from services.store.embedding_store import topic_embedding_store
from services.store.relation_store import dupe_store
from services.socket_manager import ws_manager
from services.topic_manager import topic_manager
from services.duplicate.duplicate_service import duplicate_service



class DupeManager:
    """Detects, stores, and resolves potential duplicate topics."""

    def __init__(self, store=dupe_store):
        self.store = store
        self.id_thresh = config.ID_THRESH
        self.delay = config.DUPE_CHECK_DELAY

    async def check_new_topic(self, topic: str, embedding: List[float]):
        """Schedule a delayed check when a new topic is embedded."""
        if hasattr(embedding, "tolist"):
            embedding = embedding.tolist()
        asyncio.create_task(self._delayed_check(topic, embedding))

    async def _delayed_check(self, topic: str, embedding: List[float]):
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

                score = await duplicate_service.hybrid_score(topic, embedding, other, rec["embedding"])
                if score >= self.id_thresh:
                    record = self.add_candidate(topic, other, score)
                    await ws_manager.broadcast({
                        "event_type": "duplicate",
                        "data": record
                    })
                    return  

        print(f"[DupeManager] No duplicates found for {topic} after retries.")


    def add_candidate(self, topic_a: str, topic_b: str, score: float) -> dict:
        """Add a duplicate candidate if not already stored."""
        existing = self.find_pair(topic_a, topic_b)
        if existing:
            return existing

        record = {
            "topics": [topic_a, topic_b],
            "score": score,
            "status": "PENDING",
        }
        self.store.add(record)
        return record

    def confirm_duplicate(
        self,
        topic_a: str,
        topic_b: str,
        target: str | None = None,
    ) -> Optional[dict]:
        """Confirm a duplicate pair and unsubscribe one of the topics."""
        rec = self.find_pair(topic_a, topic_b)
        if not rec:
            return None

        target = target or topic_b
        if target not in {topic_a, topic_b}:
            raise ValueError("Unsubscribe target must be one of the duplicate topics")
        topic_manager.unsubscribe(target)
        return self.store.update_status(
            topic_a,
            topic_b,
            "CONFIRMED_DUPLICATE",
        )

    def keep_both(self, topic_a: str, topic_b: str) -> Optional[dict]:
        """Mark a pair as not duplicates and keep both topics."""
        rec = self.find_pair(topic_a, topic_b)
        if not rec:
            return None

        return self.store.update_status(topic_a, topic_b, "NOT_DUPLICATE")

    def find_pair(self, topic_a: str, topic_b: str) -> Optional[dict]:
        """Find a stored duplicate pair, if it exists."""
        for rec in self.store.get_all():
            if {rec["topics"][0], rec["topics"][1]} == {topic_a, topic_b}:
                return rec
        return None

    def list_pending(self) -> List[dict]:
        """Return all pending duplicate pairs."""
        return [r for r in self.store.get_all() if r["status"] == "PENDING"]


# Singleton instance
dupe_manager = DupeManager()
