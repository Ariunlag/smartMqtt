import logging

from services.mqtt.client import mqtt_client

from .store.canonical_identity_store import canonical_identity_store
from .store.topic_store import ignored_topic_store, topic_store

logger = logging.getLogger(__name__)


class DuplicateAliasSubscriptionError(ValueError):
    """Raised when a confirmed alias is manually reactivated."""


class TopicManager:
    """Manages MQTT topic subscriptions, including ignored topics and prefix stripping."""

    def __init__(self, identity_store=canonical_identity_store):
        self.identity_store = identity_store

    def subscribe(self, topic: str):
        """Subscribe to a topic and store it (prefix-safe)."""
        identity = self.identity_store.get(topic)
        if identity.is_alias:
            raise DuplicateAliasSubscriptionError(
                f"Topic '{topic}' is a duplicate alias of canonical topic "
                f"'{identity.canonical_topic}'"
            )
        ignored = ignored_topic_store.get_all()

        if topic in ignored:
            logger.info("Skipping subscribe for ignored topic: %s", topic)
            return

        mqtt_client.subscribe(topic)
        topic_store.add(topic)
        logger.info("Subscribed to %s", topic)

    def unsubscribe(self, topic: str) -> bool:
        """Unsubscribe and remove from store."""
        topics = topic_store.get_all()

        identity = self.identity_store.get(topic)
        if topic in topics or identity.is_alias:
            mqtt_client.unsubscribe(topic)
            topic_store.remove(topic)
            logger.info("Unsubscribed from %s", topic)
            return True

        logger.info("Cannot unsubscribe, topic not found: %s", topic)
        return False

    def get_subscribed_topics(self) -> list[str]:
        """Return all clean (prefix-stripped) topics."""
        return topic_store.get_all()

    def resubscribe_all(self):
        """Re-subscribe to all non-ignored topics with prefix applied."""
        topics = topic_store.get_all()
        ignored = ignored_topic_store.get_all()
        identities = self.identity_store.resolve_many(topics)

        for topic in topics:
            canonical = identities.get(topic, topic)
            if canonical != topic:
                logger.info(
                    "Skipping duplicate alias %s (canonical %s)", topic, canonical
                )
            elif topic not in ignored:
                mqtt_client.subscribe(topic)
                logger.info("Resubscribed to %s", topic)
            else:
                logger.info("Skipping ignored topic %s", topic)


# Singleton
topic_manager = TopicManager()
