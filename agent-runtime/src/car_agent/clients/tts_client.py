from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class TtsNotifier:
    def __init__(
        self,
        *,
        enabled: bool,
        bridge_url: str,
        timeout_sec: float,
    ) -> None:
        self.enabled = enabled
        self.bridge_url = bridge_url
        self.timeout_sec = timeout_sec
        self._pending: set[asyncio.Task[None]] = set()

    def notify(
        self,
        text: str,
        *,
        event: str,
        priority: str = "normal",
        task_id: str | None = None,
        thread_id: str | None = None,
    ) -> None:
        if not self.enabled:
            return
        text = text.strip()
        if not text:
            return

        payload: dict[str, Any] = {
            "text": text,
            "event": event,
            "priority": priority,
        }
        if task_id:
            payload["task_id"] = task_id
        if thread_id:
            payload["thread_id"] = thread_id

        try:
            task = asyncio.create_task(self._post(payload))
        except RuntimeError:
            logger.warning("TTS notification skipped because no event loop is running")
            return
        self._pending.add(task)
        task.add_done_callback(self._finish_task)

    async def _post(self, payload: dict[str, Any]) -> None:
        async with httpx.AsyncClient(timeout=self.timeout_sec) as client:
            response = await client.post(self.bridge_url, json=payload)
            response.raise_for_status()

    def _finish_task(self, task: asyncio.Task[None]) -> None:
        self._pending.discard(task)
        try:
            task.result()
        except Exception as exc:
            logger.warning("TTS notification failed: %s", exc)
