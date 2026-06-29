"""Compatibility facade for assigning one tag representation to a group."""

from config import config
from services.store.embedding_store import tagset_store


class TagManager:
    def __init__(self, threshold: float = config.GROUP_TAG_THRESH):
        self.threshold = threshold

    def process_tag(
        self,
        tag: str,
        embedding,
        topic: str,
        tag_key: str = "value",
    ) -> str:
        vector = (
            embedding.tolist()
            if hasattr(embedding, "tolist")
            else list(embedding)
        )
        tagset_store.store_tag_embedding(topic, tag_key, str(tag), vector)
        return tagset_store.find_or_create_set(
            tag_key,
            str(tag),
            vector,
            self.threshold,
            topic,
        )


tag_manager = TagManager()
