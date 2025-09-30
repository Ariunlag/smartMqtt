import os
from config import config
from .base_store import ListStore, DictStore


class TopicStore(ListStore):
    def __init__(self):
        filepath = os.path.join(config.DATA_DIR, "topic_store.json")
        super().__init__(filepath)


class IgnoredTopicStore(ListStore):
    def __init__(self):
        filepath = os.path.join(config.DATA_DIR, "ignored_topic_store.json")
        super().__init__(filepath)


class DetectedTopicStore(ListStore):
    def __init__(self):
        filepath = os.path.join(config.DATA_DIR, "detected_topic_store.json")
        super().__init__(filepath)





# Singleton instances
topic_store = TopicStore()
ignored_topic_store = IgnoredTopicStore()
detected_topic_store = DetectedTopicStore()
