"""WebSocket connection pool and JSON event broadcasting."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger("server.ws")


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: list[WebSocket] = []
        self._lock = asyncio.Lock()

    @property
    def connection_count(self) -> int:
        return len(self._connections)

    @staticmethod
    def _envelope(event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": event_type,
            "payload": payload,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.append(websocket)
        logger.info("WebSocket 客户端已连接，当前连接数=%d", self.connection_count)
        await self.send_to(websocket, "connected", {"message": "connected"})

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            if websocket in self._connections:
                self._connections.remove(websocket)
        logger.info("WebSocket 客户端已断开，当前连接数=%d", self.connection_count)

    async def send_to(self, websocket: WebSocket, event_type: str, payload: dict[str, Any]) -> None:
        await websocket.send_json(self._envelope(event_type, payload))

    async def broadcast(self, event_type: str, payload: dict[str, Any] | None = None) -> None:
        message = self._envelope(event_type, payload or {})
        async with self._lock:
            targets = list(self._connections)
        stale: list[WebSocket] = []
        for websocket in targets:
            try:
                await websocket.send_json(message)
            except (WebSocketDisconnect, RuntimeError):
                stale.append(websocket)
            except Exception:
                logger.exception("向 WebSocket 客户端发送消息失败")
                stale.append(websocket)
        for websocket in stale:
            await self.disconnect(websocket)


ws_manager = ConnectionManager()
