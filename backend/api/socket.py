'''
websocket API endpoints
'''

import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from services.socket_manager import ws_manager

router = APIRouter(tags=["Websocket"])


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            raw = await websocket.receive_text()
            # Only handle heartbeats. Do NOT rebroadcast arbitrary client input
            # to other clients (avoids a client-to-client relay hole).
            try:
                msg = json.loads(raw)
            except (ValueError, TypeError):
                continue
            if isinstance(msg, dict) and msg.get("type") == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
