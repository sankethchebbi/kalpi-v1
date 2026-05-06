"""WebSocket route for live notifications."""
from fastapi import APIRouter, Cookie, WebSocket, WebSocketDisconnect

from app.auth import decode_access_token
from app.engine.notifier import manager

router = APIRouter()


@router.websocket("/ws/notifications")
async def notifications_ws(websocket: WebSocket, access_token: str | None = Cookie(default=None)):
    """Auth via the same JWT cookie used elsewhere. Browsers send cookies
    on the WS upgrade handshake automatically."""
    user_id = decode_access_token(access_token) if access_token else None
    if not user_id:
        await websocket.close(code=4401)  # custom close code = 'unauthorized'
        return

    await manager.connect(user_id, websocket)
    try:
        while True:
            # Pure server-push — we just need to keep the socket open.
            # Any message from the client is ignored.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(user_id, websocket)
