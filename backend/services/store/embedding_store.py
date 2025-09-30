import os
from config import config
from .base_store import DictStore
import numpy as np
from typing import List, Dict, Any


class TopicEmbeddingStore(DictStore):
    def __init__(self):
        filepath = os.path.join(config.DATA_DIR, "topic_embedding_store.json")
        super().__init__(filepath)

# Example entry:
# {
#   "topic": "home/kitchen/device1",
#   "embedding": [...],
#   "tags": {"room": "kitchen", "device": "sensor"}
# }


class TagSetStore(DictStore):
    def __init__(self):
        filepath = os.path.join(config.DATA_DIR, "tagset_store.json")
        super().__init__(filepath)

    # Example entry:
    # {
    #   "id": "set_1",
    #   "tags": ["temp", "temperature", "celsius"],
    #   "centroid": [...],
    #   "topics": ["sensor/temp", "room1/temp"]
    # }

    def find_or_create_set(self, tag: str, vec: List[float], threshold: float, topic: str) -> str:
        best_id, best_score = None, -1.0
        for s in self._data:
            centroid = np.array(s["centroid"])
            score = np.dot(vec, centroid) / (np.linalg.norm(vec) * np.linalg.norm(centroid))
            if score > best_score:
                best_id, best_score = s["id"], score

        if best_id and best_score >= threshold:
            # update existing set
            set_obj = next(s for s in self._data if s["id"] == best_id)
            if tag not in set_obj["tags"]:
                set_obj["tags"].append(tag)
            set_obj["centroid"] = (
                np.mean([set_obj["centroid"], vec], axis=0).tolist()
            )
            self.save()
            return best_id
        else:
            # create new set
            new_id = f"set_{len(self._data) + 1}"
            self.add({"id": new_id, "tags": [tag], "centroid": vec, "topics": [topic]})
            return new_id

    def add_topic_to_set(self, set_id: str, topic: str):
        set_obj = next((s for s in self._data if s["id"] == set_id), None)
        if not set_obj:
            raise ValueError(f"Set {set_id} not found")
        if "topics" not in set_obj:
            set_obj["topics"] = []
        if topic not in set_obj["topics"]:
            set_obj["topics"].append(topic)
            self.save()

    def get_all(self) -> List[Dict[str, Any]]:
        """Return minimal info for listing (id, tags)."""
        return [
            {"id": s["id"], "tags": s["tags"]}
            for s in self._data
        ]

    def get_topics(self, set_id: str) -> List[str]:
        set_obj = next((s for s in self._data if s["id"] == set_id), None)
        if not set_obj:
            return []
        return set_obj.get("topics", [])

topic_embedding_store = TopicEmbeddingStore()
tagset_store = TagSetStore()