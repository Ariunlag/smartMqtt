import asyncio
import logging
import numpy as np
from config import config
from services.embedding.base_model import BaseEmbeddingModel
from services.embedding.sentence_transformer import STEmbeddingModel
from .store.embedding_store import tagset_store, topic_embedding_store
from services.dupe_manager import dupe_manager
from services.groups_manager import groups_manager


logger = logging.getLogger(__name__)


class EmbeddingManager:
    def __init__(self, model: BaseEmbeddingModel):
        self.model = model

    async def embed_flattened_topic(self, topic: str, tags: dict):
        """Embed topic + tags into a single flat sentence vector."""
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
        logger.debug("Converted vector shape=%s", vector.shape)

        try:
            topic_embedding_store.add({
                "topic": topic,
                "embedding": vector.tolist(),
                "tags": tags
            })
            logger.debug("Stored topic embedding for %s", topic)
        except Exception:
            logger.exception("Failed to store embedding for %s", topic)
            raise

        return vector

    async def embed_tags(self, topic: str, tags: dict):
        """Embed and persist normalized tag key/value representations."""
        logger.debug("Starting embed_tags for topic=%s, tags=%s", topic, tags)
        tag_items = [
            (str(key), str(value))
            for key, value in tags.items()
            if value is not None and str(value).strip()
        ]
        tag_texts = [
            self._normalize_tag_pair(key, value)
            for key, value in tag_items
        ]
        logger.debug("Normalized tag values: %s", tag_texts)

        if not tag_texts:
            logger.debug("No tags to embed")
            return []

        loop = asyncio.get_running_loop()
        try:
            vectors = await loop.run_in_executor(None, self.model.encode, tag_texts)
            logger.debug("Raw tag vectors returned, count=%s", len(vectors))
        except Exception:
            logger.exception("Embedding failed for tags=%s", tag_texts)
            raise

        vectors = [np.array(v, dtype=float) for v in vectors]
        logger.debug("Converted tag vectors, count=%s", len(vectors))

        for (tag_key, tag_value), vec in zip(tag_items, vectors):
            tagset_store.store_tag_embedding(
                topic,
                tag_key,
                tag_value,
                vec.tolist(),
            )
            logger.debug(
                "Stored tag key/value=%s/%s, vec_dim=%s",
                tag_key, tag_value, vec.shape,
            )

        return tag_items, vectors


    async def process_new_topic(self, topic: str, tags: dict):
        """Full embedding pipeline for a new topic."""
        logger.debug("Processing new topic=%s, tags=%s", topic, tags)
        flat_vec = await self.embed_flattened_topic(topic, tags)
        logger.debug("topic embed done")

        tag_items, tag_vecs = await self.embed_tags(topic, tags)
        logger.debug("tag embed done")

        # convert vectors to lists before sending to managers
        tag_vecs_list = [vec.tolist() for vec in tag_vecs]

        try:
            await groups_manager.update_for_topic(topic, tag_items, tag_vecs_list)
            logger.debug("groups_manager updated")
        except Exception:
            logger.exception("groups_manager failed")

        try:
            await dupe_manager.check_new_topic(topic, flat_vec)
            logger.debug("dupe_manager check done")
        except Exception:
            logger.exception("dupe_manager failed")

        return {"flat": flat_vec, "tags": tag_vecs_list}


    def _normalize_topic(self, topic: str, tags: dict):
        """Convert topic path and tags into a flat descriptive string."""
        tag_str = " ".join([f"{k} {v}" for k, v in tags.items()])
        return f"{topic.replace('/', ' ')} {tag_str}"

    def _normalize_tag_value(self, value: str) -> str:
        """Basic normalization for tag values."""
        return str(value).strip().lower().replace("_", " ")

    def _normalize_tag_pair(self, key: str, value: str) -> str:
        return (
            f"{self._normalize_tag_value(key)} "
            f"{self._normalize_tag_value(value)}"
        )

embedding_manager = EmbeddingManager(STEmbeddingModel(config.EMBEDDING_MODEL))
