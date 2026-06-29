from services.mqtt.client import mqtt_client
from .store.topic_store import ignored_topic_store, topic_store


class TopicManager:
    """Manages MQTT topic subscriptions, including ignored topics and prefix stripping."""
    def __init__(self):
        pass
    
    def subscribe(self, topic: str):
        """Subscribe to a topic and store it (prefix-safe)."""
        ignored = ignored_topic_store.get_all()

        if topic in ignored:
            print(f"[TopicManager] Skipping subscribe for ignored topic: {topic}")
            return

        mqtt_client.subscribe(topic)
        topic_store.add(topic)
        print(f"[TopicManager] Subscribed to {topic} (stored as {topic})")

    def unsubscribe(self, topic: str) -> bool:
        """Unsubscribe and remove from store."""
        topics = topic_store.get_all()

        if topic in topics:
            mqtt_client.unsubscribe(topic)
            topic_store.remove(topic)
            print(f"[TopicManager] Unsubscribed from {topic}")
            return True

        print(f"[TopicManager] Cannot unsubscribe, topic not found: {topic}")
        return False

    def get_subscribed_topics(self) -> list[str]:
        """Return all clean (prefix-stripped) topics."""
        return topic_store.get_all()

    def resubscribe_all(self):
        """Re-subscribe to all non-ignored topics with prefix applied."""
        topics = topic_store.get_all()
        ignored = ignored_topic_store.get_all()

        for topic in topics:
            if topic not in ignored:
                mqtt_client.subscribe(topic)
                print(f"[TopicManager] Resubscribed to {topic}")
            else:
                print(f"[TopicManager] Skipping ignored topic {topic}")


# Singleton
topic_manager = TopicManager()
