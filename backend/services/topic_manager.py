from services.mqtt.client import mqtt_client
from .store.topic_store import topic_store, ignored_topic_store, detected_topic_store


""" Manages MQTT topic subscriptions, including handling ignored topics. """

class TopicManager:
    def __init__(self):
        pass
    def subscribe(self, topic: str):
        ignored = ignored_topic_store.get_all()
        if topic in ignored:
            print(f"[TopicManager] Skipping subscribe for ignored topic: {topic}")
            return
        mqtt_client.subscribe(topic)
        topic_store.add(topic)

    def unsubscribe(self, topic: str) -> bool:
        topics = topic_store.get_all()
        if topic in topics:
            mqtt_client.unsubscribe(topic)
            topic_store.remove(topic)
            return True
        print(f"[TopicManager] Cannot unsubscribe, topic not found: {topic}")
        return False

    def get_subscribed_topics(self) -> list[str]:
        return topic_store.get_all()

    def resubscribe_all(self):
        topics = topic_store.get_all()
        ignored = ignored_topic_store.get_all()
        for topic in topics:
            if topic not in ignored:
                mqtt_client.subscribe(topic)
            else:
                print(f"[TopicManager] Skipping ignored topic {topic}")

topic_manager = TopicManager()
