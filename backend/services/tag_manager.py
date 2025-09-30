from typing import List
import numpy as np
from utils.similarity import cosine_similarity
from .store.embedding_store import tagset_store


class TagManager:
    def __init__(self, threshold: float = 0.8):
        """
        :param threshold: cosine similarity threshold for clustering tags
        """
        self.threshold = threshold

    def process_tag(self, tag: str, embedding: np.ndarray, topic: str) -> str:
        """
        Assign a tag to an existing set or create a new one.
        Also ensures the topic is linked to the tag set.
        """
        emb = np.array(embedding, dtype=float)

        sets = tagset_store._data or []  # full records (id, tags, centroid, topics)

        # check if tag already exists in a set
        for s in sets:
            if tag in s["tags"]:
                tagset_store.add_topic_to_set(s["id"], topic)
                return s["id"]

        # try to find a matching set by centroid similarity
        for s in sets:
            centroid = np.array(s["centroid"], dtype=float)
            sim = cosine_similarity(emb, centroid)
            if sim >= self.threshold:
                # add new tag to existing set
                if tag not in s["tags"]:
                    s["tags"].append(tag)

                # incremental centroid update
                n = len(s["tags"])
                s["centroid"] = ((centroid * (n - 1)) + emb) / n
                s["centroid"] = s["centroid"].tolist()

                tagset_store.save()
                tagset_store.add_topic_to_set(s["id"], topic)
                return s["id"]

        # no match → create a new set
        new_id = f"set_{len(sets) + 1}"
        new_set = {
            "id": new_id,
            "tags": [tag],
            "centroid": emb.tolist(),
            "topics": [topic],
        }
        tagset_store.add(new_set)
        return new_id

    def get_topics(self, set_id: str) -> List[str] | None:
        set_obj = next((s for s in self._data if s["id"] == set_id), None)
        if not set_obj:
            return None   # instead of []
        return set_obj.get("topics", [])



tag_manager = TagManager()
