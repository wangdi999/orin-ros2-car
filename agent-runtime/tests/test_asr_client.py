from __future__ import annotations

import base64
from typing import Any

import pytest

from car_agent.clients.asr_client import MimoSpeechRecognizer


@pytest.mark.asyncio
async def test_mimo_speech_recognizer_posts_input_audio(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {"choices": [{"message": {"content": "向前移动十厘米"}}]}

    class FakeClient:
        def __init__(self, *, timeout: float) -> None:
            self.timeout = timeout

        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def post(
            self,
            url: str,
            *,
            json: dict[str, Any],
            headers: dict[str, str],
        ) -> FakeResponse:
            calls.append({"url": url, "json": json, "headers": headers, "timeout": self.timeout})
            return FakeResponse()

    monkeypatch.setattr("car_agent.clients.asr_client.httpx.AsyncClient", FakeClient)

    recognizer = MimoSpeechRecognizer(
        base_url="https://api.xiaomimimo.com/v1",
        model="mimo-v2.5-asr",
        api_key="secret",
        timeout_sec=12,
    )
    result = await recognizer.transcribe(
        audio_base64=base64.b64encode(b"audio").decode("ascii"),
        audio_format="audio/webm;codecs=opus",
        language="zh-CN",
    )

    assert result.text == "向前移动十厘米"
    assert calls[0]["url"] == "https://api.xiaomimimo.com/v1/chat/completions"
    assert calls[0]["headers"]["Authorization"] == "Bearer secret"
    content = calls[0]["json"]["messages"][0]["content"]
    assert content[1]["type"] == "input_audio"
    assert content[1]["input_audio"]["format"] == "webm"


@pytest.mark.asyncio
async def test_mimo_speech_recognizer_accepts_root_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    urls: list[str] = []

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {"choices": [{"message": {"content": "停止"}}]}

    class FakeClient:
        def __init__(self, *, timeout: float) -> None:
            self.timeout = timeout

        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def post(
            self,
            url: str,
            *,
            json: dict[str, Any],
            headers: dict[str, str],
        ) -> FakeResponse:
            del json, headers
            urls.append(url)
            return FakeResponse()

    monkeypatch.setattr("car_agent.clients.asr_client.httpx.AsyncClient", FakeClient)

    recognizer = MimoSpeechRecognizer(
        base_url="https://api.xiaomimimo.com",
        model="mimo-v2.5-asr",
        api_key="secret",
        timeout_sec=12,
    )
    await recognizer.transcribe(
        audio_base64=base64.b64encode(b"audio").decode("ascii"),
        audio_format="webm",
    )

    assert urls == ["https://api.xiaomimimo.com/v1/chat/completions"]
