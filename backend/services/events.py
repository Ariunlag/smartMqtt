"""Versioned WebSocket event envelope.

Kept dependency-free so it can be unit tested without FastAPI/DB clients.
"""

import uuid
from datetime import datetime, timezone
from typing import Any

EVENT_SCHEMA_VERSION = 1


def make_envelope(
    event_type: str | None,
    data: Any,
    *,
    event_id: str | None = None,
    occurred_at: str | None = None,
) -> dict[str, Any]:
    """Wrap an event in the versioned envelope broadcast to WebSocket clients.

    Fields: version, event_id, event_type, occurred_at (ISO-8601 UTC), data.
    """
    return {
        "version": EVENT_SCHEMA_VERSION,
        "event_id": event_id or str(uuid.uuid4()),
        "event_type": event_type,
        "occurred_at": occurred_at or datetime.now(timezone.utc).isoformat(),
        "data": data,
    }
