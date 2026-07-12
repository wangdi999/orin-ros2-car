from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import WebSocket


class EventHub:
    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._clients.add(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(websocket)

    async def broadcast(
        self,
        event_type: str,
        data: dict[str, Any],
        *,
        task_id: str | None = None,
        thread_id: str | None = None,
    ) -> None:
        payload = {
            "event_id": str(uuid4()),
            "type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "task_id": task_id,
            "thread_id": thread_id,
            "data": data,
        }
        stale: list[WebSocket] = []
        async with self._lock:
            clients = list(self._clients)
        for websocket in clients:
            try:
                await websocket.send_json(payload)
            except Exception:
                stale.append(websocket)
        if stale:
            async with self._lock:
                for websocket in stale:
                    self._clients.discard(websocket)
