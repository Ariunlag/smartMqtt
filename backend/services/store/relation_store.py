import os
from config import config
from .base_store import DictStore

class ClassStore(DictStore):
    def __init__(self):
        filepath = os.path.join(config.DATA_DIR, "class_store.json")
        super().__init__(filepath, key_field="name")
# Example entry:
# {
#   "name": "sensor",
#   "topics": ["home/kitchen/device1", "home/livingroom/device2"]
# }


class DupeStore(DictStore):
    def __init__(self):
        filepath = os.path.join(config.DATA_DIR, "dupe_store.json")
        super().__init__(filepath)

# Example entry:
# {
#   "topic_a": "home/kitchen/device1",
#   "topic_b": "home/kitchen/deviceX",
#   "score": 0.96,
#   "status": DupeStatus.PENDING
# }


# Singleton instances
class_store = ClassStore()
dupe_store = DupeStore()