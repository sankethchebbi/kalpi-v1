"""In-memory notification dispatcher.

Two channels:
  - console: always on, prints to stdout
  - websocket: per-user fanout to clients connected on /ws/notifications

Single-process design — no Redis pub/sub needed for the assignment scope.
If you ever need multi-worker, swap the in-memory dict for Redis pub/sub
without changing any caller.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger("notifier")
logger.setLevel(logging.INFO)


class ConnectionManager:
    """Per-user registry of active WebSocket connections.

    A single user can have multiple tabs open — broadcast hits all of them.
    """

    def __init__(self) -> None:
        self._connections: dict[int, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def connect(self, user_id: int, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._connections[user_id].add(ws)
        logger.info(f"WS connected user={user_id} total_for_user={len(self._connections[user_id])}")

    async def disconnect(self, user_id: int, ws: WebSocket) -> None:
        async with self._lock:
            self._connections[user_id].discard(ws)
            if not self._connections[user_id]:
                self._connections.pop(user_id, None)
        logger.info(f"WS disconnected user={user_id}")

    async def broadcast_to_user(self, user_id: int, message: dict[str, Any]) -> None:
        """Send `message` (JSON-serializable) to every active socket for the user.
        Dead connections are silently dropped."""
        payload = json.dumps(message)
        dead: list[WebSocket] = []
        async with self._lock:
            sockets = list(self._connections.get(user_id, ()))
        for ws in sockets:
            try:
                await ws.send_text(payload)
            except Exception as e:
                logger.warning(f"WS send failed user={user_id}: {e}")
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._connections[user_id].discard(ws)


# Module-level singleton — same instance imported everywhere
manager = ConnectionManager()


def log_to_console(event: str, payload: dict[str, Any]) -> None:
    """Always-on console channel. Structured for easy grep."""
    logger.info(f"[NOTIFY] event={event} payload={json.dumps(payload, default=str)}")


async def notify_batch_complete(user_id: int, batch_summary: dict[str, Any]) -> None:
    """Fire both channels (console + WS) when a batch finishes."""
    log_to_console("batch_complete", batch_summary)
    await manager.broadcast_to_user(
        user_id, {"event": "batch_complete", "data": batch_summary}
    )
