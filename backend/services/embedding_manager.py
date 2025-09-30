import asyncio
import numpy as np
from services.embedding.base_model import BaseEmbeddingModel
from services.embedding.sentence_transformer import STEmbeddingModel
from services.tag_manager import tag_manager
from .store.embedding_store import topic_embedding_store
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

    async def embed_tags(self, tags: dict):
        """Embed individual tag values separately and register them in TagManager."""
        print(f"[DEBUG] Starting embed_tags with tags={tags}")
        tag_texts = [self._normalize_tag_value(v) for v in tags.values() if v]
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

        for raw_value, vec in zip(tags.values(), vectors):
            if raw_value:  # avoid None/empty
                try:
                    tag_manager.process_tag(str(raw_value), vec)
                    print(f"[DEBUG] Processed tag={raw_value}, vec_dim={vec.shape}")
                except Exception as e:
                    print(f"[ERROR] TagManager failed for tag={raw_value}, error: {e}")

        return vectors

    async def process_new_topic(self, topic: str, tags: dict):
        """Full embedding pipeline for a new topic."""
        print(f"[DEBUG] Processing new topic={topic}, tags={tags}")
        flat_vec = await self.embed_flattened_topic(topic, tags)
        print("[DEBUG] topic embed done")

        tag_vecs = await self.embed_tags(tags)
        print("[DEBUG] tag embed done")

        # convert vectors to lists before sending to managers
        tag_vecs_list = [vec.tolist() for vec in tag_vecs]

        try:
            await groups_manager.update_for_topic(topic, tags, tag_vecs_list)
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


embedding_manager = EmbeddingManager(STEmbeddingModel("all-MiniLM-L6-v2"))
