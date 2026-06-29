from typing import List
from fastapi import WebSocket
import json

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
        """Broadcast a structured JSON payload to all active clients."""
        message = json.dumps(payload)
        failed = []
        for connection in list(self.active_connections):
            try:
                await connection.send_text(message)
            except Exception:
                failed.append(connection)
        for connection in failed:
            self.disconnect(connection)


ws_manager = WebSocketManager()
