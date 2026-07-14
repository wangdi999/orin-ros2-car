from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from car_agent.api.app import create_app
from car_agent.clients.tts_client import TtsNotifier
from car_agent.config import Settings


class FakeTtsNotifier:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def notify(
        self,
        text: str,
        *,
        event: str,
        priority: str = "normal",
        task_id: str | None = None,
        thread_id: str | None = None,
    ) -> None:
        self.calls.append(
            {
                "text": text,
                "event": event,
                "priority": priority,
                "task_id": task_id,
                "thread_id": thread_id,
            }
        )


def _settings(tmp_path: Path) -> Settings:
    locations = tmp_path / "locations.yaml"
    locations.write_text(
        """
locations:
  - location_id: home
    display_name: 起点
    x: 0
    y: 0
    yaw: 0
    enabled: true
  - location_id: east_gate
    display_name: 东门
    x: 1
    y: 0
    yaw: 0
    enabled: true
""".strip(),
        encoding="utf-8",
    )
    return Settings(
        CAR_AGENT_TOKEN="test-token",
        CAR_AGENT_DATABASE_PATH=tmp_path / "agent.db",
        CAR_AGENT_CHECKPOINT_PATH=tmp_path / "checkpoints.db",
        CAR_AGENT_LOCATIONS_PATH=locations,
        CAR_AGENT_GATEWAY_MODE="mock",
        LLM_PROVIDER="mock",
        TTS_ENABLED=True,
    )


def test_agent_workflow_emits_tts_notifications(tmp_path: Path) -> None:
    fake_tts = FakeTtsNotifier()
    headers = {"Authorization": "Bearer test-token"}

    with TestClient(create_app(_settings(tmp_path))) as client:
        client.app.state.tts_notifier = fake_tts
        created = client.post(
            "/api/v1/agent/requests",
            headers=headers,
            json={"text": "巡检东门，最后返回起点", "user_id": "tester"},
        )
        assert created.status_code == 200

        thread_id = created.json()["thread_id"]
        resumed = client.post(
            f"/api/v1/agent/threads/{thread_id}/resume",
            headers=headers,
            json={"decision": "APPROVE", "operator": "tester"},
        )
        assert resumed.status_code == 200

        task_id = resumed.json()["task_id"]
        completed = client.post(
            f"/api/v1/agent/threads/{thread_id}/events",
            headers=headers,
            json={"event_id": "evt-tts-1", "event_type": "TASK_SUCCEEDED"},
        )
        assert completed.status_code == 200

    assert [call["event"] for call in fake_tts.calls] == [
        "AGENT_REQUEST_RECEIVED",
        "APPROVAL_REQUIRED",
        "TASK_APPROVED",
        "TASK_SUCCEEDED",
    ]
    assert fake_tts.calls[0]["text"] == "已收到巡检指令，正在生成计划。"
    assert fake_tts.calls[2]["task_id"] == task_id
    assert fake_tts.calls[3]["text"] == "巡检任务已完成。"


@pytest.mark.asyncio
async def test_tts_notifier_posts_without_blocking(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

    class FakeClient:
        def __init__(self, *, timeout: float) -> None:
            self.timeout = timeout

        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def post(self, url: str, *, json: dict[str, Any]) -> FakeResponse:
            calls.append({"url": url, "json": json, "timeout": self.timeout})
            return FakeResponse()

    monkeypatch.setattr("car_agent.clients.tts_client.httpx.AsyncClient", FakeClient)

    notifier = TtsNotifier(
        enabled=True,
        bridge_url="http://127.0.0.1:8123/speak",
        timeout_sec=0.5,
    )
    notifier.notify(
        "任务已批准，开始执行巡检。",
        event="TASK_APPROVED",
        task_id="task-1",
        thread_id="thread-1",
    )

    while notifier._pending:
        await asyncio.sleep(0)

    assert calls == [
        {
            "url": "http://127.0.0.1:8123/speak",
            "json": {
                "text": "任务已批准，开始执行巡检。",
                "event": "TASK_APPROVED",
                "priority": "normal",
                "task_id": "task-1",
                "thread_id": "thread-1",
            },
            "timeout": 0.5,
        }
    ]


@pytest.mark.asyncio
async def test_tts_notifier_disabled_does_not_post(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_client(*args: object, **kwargs: object) -> None:
        raise AssertionError("http client should not be created")

    monkeypatch.setattr("car_agent.clients.tts_client.httpx.AsyncClient", fail_client)
    notifier = TtsNotifier(
        enabled=False,
        bridge_url="http://127.0.0.1:8123/speak",
        timeout_sec=0.5,
    )

    notifier.notify("不会播报", event="DISABLED")
    await asyncio.sleep(0)

    assert notifier._pending == set()
