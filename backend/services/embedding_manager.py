import asyncio
import numpy as np
from config import config
from services.embedding.base_model import BaseEmbeddingModel
from services.embedding.sentence_transformer import STEmbeddingModel
from .store.embedding_store import tagset_store, topic_embedding_store
from services.dupe_manager import dupe_manager
from services.groups_manager import groups_manager


class EmbeddingManager:
    def __init__(self, model: BaseEmbeddingModel):
        self.model = model

    async def embed_flattened_topic(self, topic: str, tags: dict):
        """Embed topic + tags into a single flat sentence vector."""
        print(f"[DEBUG] Starting embed_flattened_topic for topic={topic}, tags={tags}")
        sentence = self._normalize_topic(topic, tags)
        print(f"[DEBUG] Normalized sentence: {sentence}")

        loop = asyncio.get_running_loop()
        try:
            vector = await loop.run_in_executor(None, self.model.encode, [sentence])
            print(f"[DEBUG] Raw vector returned, shape={np.array(vector).shape}")
        except Exception as e:
            print(f"[ERROR] Embedding failed for topic={topic} with error: {e}")
            raise

        vector = np.array(vector[0], dtype=float)
        print(f"[DEBUG] Converted vector shape={vector.shape}")

        try:
            topic_embedding_store.add({
                "topic": topic,
                "embedding": vector.tolist(),
                "tags": tags
            })
            print(f"[DEBUG] Stored topic embedding for {topic}")
        except Exception as e:
            print(f"[ERROR] Failed to store embedding for {topic}: {e}")
            raise

        return vector

    async def embed_tags(self, topic: str, tags: dict):
        """Embed and persist normalized tag key/value representations."""
        print(f"[DEBUG] Starting embed_tags for topic={topic}, tags={tags}")
        tag_items = [
            (str(key), str(value))
            for key, value in tags.items()
            if value is not None and str(value).strip()
        ]
        tag_texts = [
            self._normalize_tag_pair(key, value)
            for key, value in tag_items
        ]
        print(f"[DEBUG] Normalized tag values: {tag_texts}")

        if not tag_texts:
            print("[DEBUG] No tags to embed")
            return []

        loop = asyncio.get_running_loop()
        try:
            vectors = await loop.run_in_executor(None, self.model.encode, tag_texts)
            print(f"[DEBUG] Raw tag vectors returned, count={len(vectors)}")
        except Exception as e:
            print(f"[ERROR] Embedding failed for tags={tag_texts}, error: {e}")
            raise

        vectors = [np.array(v, dtype=float) for v in vectors]
        print(f"[DEBUG] Converted tag vectors, count={len(vectors)}")

        for (tag_key, tag_value), vec in zip(tag_items, vectors):
            tagset_store.store_tag_embedding(
                topic,
                tag_key,
                tag_value,
                vec.tolist(),
            )
            print(
                f"[DEBUG] Stored tag key/value={tag_key}/{tag_value}, "
                f"vec_dim={vec.shape}"
            )

        return tag_items, vectors


    async def process_new_topic(self, topic: str, tags: dict):
        """Full embedding pipeline for a new topic."""
        print(f"[DEBUG] Processing new topic={topic}, tags={tags}")
        flat_vec = await self.embed_flattened_topic(topic, tags)
        print("[DEBUG] topic embed done")

        tag_items, tag_vecs = await self.embed_tags(topic, tags)
        print("[DEBUG] tag embed done")

        # convert vectors to lists before sending to managers
        tag_vecs_list = [vec.tolist() for vec in tag_vecs]

        try:
            await groups_manager.update_for_topic(topic, tag_items, tag_vecs_list)
            print("[DEBUG] groups_manager updated")
        except Exception as e:
            print(f"[ERROR] groups_manager failed: {e}")

        try:
            await dupe_manager.check_new_topic(topic, flat_vec)
            print("[DEBUG] dupe_manager check done")
        except Exception as e:
            print(f"[ERROR] dupe_manager failed: {e}")

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
