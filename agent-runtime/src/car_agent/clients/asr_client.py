from __future__ import annotations

import base64
from typing import Any

import httpx

from car_agent.models.motion import SpeechTranscriptionResult


class MimoSpeechRecognizer:
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str,
        timeout_sec: float,
    ) -> None:
        if not base_url or not model or not api_key:
            raise ValueError("ASR configuration is incomplete")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout_sec = timeout_sec

    async def transcribe(
        self,
        *,
        audio_base64: str,
        audio_format: str,
        language: str | None = None,
    ) -> SpeechTranscriptionResult:
        audio_bytes = base64.b64decode(_strip_data_url(audio_base64), validate=True)
        if not audio_bytes:
            raise ValueError("audio is empty")
        if len(audio_bytes) > 12 * 1024 * 1024:
            raise ValueError("audio is too large")

        body: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": _prompt(language),
                        },
                        {
                            "type": "input_audio",
                            "input_audio": {
                                "data": base64.b64encode(audio_bytes).decode("ascii"),
                                "format": _normalize_audio_format(audio_format),
                            },
                        },
                    ],
                }
            ],
            "temperature": 0,
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        async with httpx.AsyncClient(timeout=self.timeout_sec) as client:
            response = await client.post(
                chat_completions_url(self.base_url),
                json=body,
                headers=headers,
            )
            response.raise_for_status()
        text = _extract_transcript(response.json()).strip()
        return SpeechTranscriptionResult(
            ok=bool(text),
            text=text,
            language=language,
            duration_sec=None,
            model=self.model,
        )


def _prompt(language: str | None) -> str:
    if language:
        return f"请转写这段语音，只输出转写文本。语言偏好：{language}。"
    return "请转写这段语音，只输出转写文本。"


def _normalize_audio_format(value: str) -> str:
    normalized = value.strip().lower().split(";")[0].split("/")[-1]
    aliases = {
        "x-wav": "wav",
        "wave": "wav",
        "mpeg": "mp3",
        "mp4": "mp4",
        "webm": "webm",
        "ogg": "ogg",
    }
    return aliases.get(normalized, normalized or "wav")


def _strip_data_url(value: str) -> str:
    text = value.strip()
    if text.startswith("data:") and "," in text:
        return text.split(",", 1)[1]
    return text


def _extract_transcript(payload: dict[str, Any]) -> str:
    choices = payload.get("choices") or []
    if not choices:
        raise RuntimeError("ASR response does not contain choices")
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                value = item.get("text") or item.get("transcript")
                if isinstance(value, str):
                    parts.append(value)
        if parts:
            return "".join(parts)
    raise RuntimeError("ASR response does not contain transcript text")


def chat_completions_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    if base.endswith("/v1"):
        return f"{base}/chat/completions"
    return f"{base}/v1/chat/completions"
