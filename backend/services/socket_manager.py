from typing import List
from fastapi import WebSocket
import json

from services.events import make_envelope


class WebSocketManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, payload: dict):
        """Broadcast an event to all clients inside a versioned envelope.

        Accepts the existing ``{"event_type": ..., "data": ...}`` shape used by
        callers and wraps it so the payload gains version/event_id/occurred_at
        while remaining backward compatible (event_type and data still present).
        """
        envelope = make_envelope(payload.get("event_type"), payload.get("data"))
        message = json.dumps(envelope)
        failed = []
        for connection in list(self.active_connections):
            try:
                await connection.send_text(message)
            except Exception:
                failed.append(connection)
        for connection in failed:
            self.disconnect(connection)


ws_manager = WebSocketManager()
