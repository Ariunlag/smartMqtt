import asyncio
import logging

import numpy as np

from config import config
from services.dupe_manager import dupe_manager
from services.embedding.base_model import BaseEmbeddingModel
from services.embedding.sentence_transformer import STEmbeddingModel
from services.store.embedding_store import topic_embedding_store

logger = logging.getLogger(__name__)


class EmbeddingManager:
    """Own the one stream-level embedding used by duplicate/context workflows."""

    def __init__(self, model: BaseEmbeddingModel):
        self.model = model

    async def embed_flattened_topic(self, topic: str, tags: dict):
        """Embed topic + tags into the authoritative stream-context vector."""
        logger.debug("Starting embed_flattened_topic for topic=%s, tags=%s", topic, tags)
        sentence = self._normalize_topic(topic, tags)
        logger.debug("Normalized sentence: %s", sentence)

        loop = asyncio.get_running_loop()
        try:
            vector = await loop.run_in_executor(None, self.model.encode, [sentence])
            logger.debug("Raw vector returned, shape=%s", np.array(vector).shape)
        except Exception:
            logger.exception("Embedding failed for topic=%s", topic)
            raise

        vector = np.array(vector[0], dtype=float)
        try:
            topic_embedding_store.add(
                {
                    "topic": topic,
                    "embedding": vector.tolist(),
                    "tags": tags,
                }
            )
        except Exception:
            logger.exception("Failed to store embedding for %s", topic)
            raise
        return vector

    async def process_new_topic(self, topic: str, tags: dict):
        """Materialize stream context and trigger duplicate detection for a new topic.

        Tag/field pair embeddings are produced once by the recommendation evidence
        sidecar. Recommendation strategies consume those stored pair vectors directly;
        this manager does not create a second tag-specific embedding pipeline.
        """
        logger.debug("Processing new topic=%s, tags=%s", topic, tags)
        flat_vec = await self.embed_flattened_topic(topic, tags)

        try:
            await dupe_manager.check_new_topic(topic, flat_vec)
        except Exception:
            logger.exception("dupe_manager failed")

        return {"flat": flat_vec}

    @staticmethod
    def _normalize_topic(topic: str, tags: dict) -> str:
        tag_str = " ".join(f"{key} {value}" for key, value in tags.items())
        return f"{topic.replace('/', ' ')} {tag_str}"


embedding_manager = EmbeddingManager(STEmbeddingModel(config.EMBEDDING_MODEL))
