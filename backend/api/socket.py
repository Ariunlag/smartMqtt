'''
websocket API endpoints
'''

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from services.socket_manager import ws_manager

router = APIRouter(tags=["Websocket"])

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            await ws_manager.broadcast({
                "event_type": "message",
                "data": data,
            })
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
