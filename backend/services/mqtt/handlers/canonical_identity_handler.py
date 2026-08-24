"""Early lifecycle gate for inactive duplicate aliases."""

import asyncio
import logging

from services.store.canonical_identity_store import canonical_identity_store

from ..base_handler import BaseHandler

logger = logging.getLogger(__name__)


class CanonicalIdentityHandler(BaseHandler):
    handler_identity = "canonical-identity"

    def __init__(self, identity_store=canonical_identity_store) -> None:
        self.identity_store = identity_store

    async def handle_message(self, message):
        identity = await asyncio.to_thread(self.identity_store.get, message.topic)
        if identity.is_alias:
            logger.warning(
                "[CanonicalIdentityHandler] Dropped inactive alias topic=%s canonical=%s",
                message.topic,
                identity.canonical_topic,
            )
            return False
        return True
