#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import queue
import shutil
import subprocess
import tempfile
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger("mimo-tts-bridge")


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value


def truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def chat_completions_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    if base.endswith("/v1"):
        return f"{base}/chat/completions"
    return f"{base}/v1/chat/completions"


def find_audio_data(response: dict[str, Any]) -> str:
    choices = response.get("choices") or []
    if not choices:
        raise RuntimeError("MiMo TTS response does not contain choices")
    message = choices[0].get("message") or {}
    audio = message.get("audio")
    if isinstance(audio, dict):
        data = audio.get("data") or audio.get("base64")
    else:
        data = audio
    if not isinstance(data, str) or not data:
        raise RuntimeError("MiMo TTS response does not contain audio data")
    if "," in data and data.lstrip().startswith("data:"):
        data = data.split(",", 1)[1]
    return data


class BridgeConfig:
    def __init__(self) -> None:
        self.enabled = truthy(os.getenv("TTS_ENABLED", "true"))
        self.host = os.getenv("TTS_BRIDGE_HOST", "127.0.0.1")
        self.port = int(os.getenv("TTS_BRIDGE_PORT", "8123"))
        self.base_url = (
            os.getenv("TTS_BASE_URL")
            or os.getenv("MIMO_BASE_URL")
            or os.getenv("LLM_BASE_URL")
            or ""
        )
        self.api_key = (
            os.getenv("TTS_API_KEY")
            or os.getenv("MIMO_API_KEY")
            or os.getenv("LLM_API_KEY")
            or ""
        )
        self.model = os.getenv("TTS_MODEL") or os.getenv("MIMO_TTS_MODEL") or "mimo-v2.5-tts"
        self.voice = os.getenv("TTS_VOICE", "mimo_default")
        self.audio_format = os.getenv("TTS_AUDIO_FORMAT", "wav")
        self.timeout_sec = float(os.getenv("TTS_API_TIMEOUT_SEC", "30"))
        self.max_text_chars = int(os.getenv("TTS_MAX_TEXT_CHARS", "120"))
        self.player_cmd = os.getenv("TTS_PLAYER_CMD", "")

    def validate_for_synthesis(self) -> None:
        if not self.base_url:
            raise RuntimeError("TTS_BASE_URL or LLM_BASE_URL is required")
        if not self.api_key:
            raise RuntimeError("TTS_API_KEY, MIMO_API_KEY or LLM_API_KEY is required")


class MimoTtsBridge:
    def __init__(self, config: BridgeConfig) -> None:
        self.config = config
        self.items: queue.Queue[dict[str, Any]] = queue.Queue()
        self.worker = threading.Thread(target=self._worker_loop, daemon=True)

    def start(self) -> None:
        self.worker.start()

    def enqueue(self, payload: dict[str, Any]) -> int:
        self.items.put(payload)
        return self.items.qsize()

    def _worker_loop(self) -> None:
        while True:
            payload = self.items.get()
            try:
                self._handle(payload)
            except Exception:
                LOGGER.exception("failed to synthesize or play TTS")
            finally:
                self.items.task_done()

    def _handle(self, payload: dict[str, Any]) -> None:
        text = str(payload.get("text", "")).strip()
        if not text:
            return
        if not self.config.enabled:
            LOGGER.info("TTS disabled, skipped: %s", text)
            return
        self.config.validate_for_synthesis()
        text = text[: self.config.max_text_chars]
        audio = self._synthesize(text)
        self._play(audio)

    def _synthesize(self, text: str) -> bytes:
        body: dict[str, Any] = {
            "model": self.config.model,
            "messages": [{"role": "assistant", "content": text}],
            "modalities": ["audio"],
            "audio": {"format": self.config.audio_format},
        }
        if self.config.voice:
            body["audio"]["voice"] = self.config.voice

        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            chat_completions_url(self.config.base_url),
            data=data,
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_sec) as response:
                response_body = response.read()
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"MiMo TTS HTTP {exc.code}: {error_body}") from exc

        decoded = json.loads(response_body.decode("utf-8"))
        audio_base64 = find_audio_data(decoded)
        return base64.b64decode(audio_base64)

    def _play(self, audio: bytes) -> None:
        suffix = f".{self.config.audio_format.strip().lower() or 'wav'}"
        with tempfile.NamedTemporaryFile(prefix="mimo-tts-", suffix=suffix, delete=False) as temp:
            temp.write(audio)
            temp_path = Path(temp.name)
        try:
            command = self._player_command(temp_path)
            LOGGER.info("playing TTS with %s", command[0])
            subprocess.run(command, check=True)
        finally:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass

    def _player_command(self, path: Path) -> list[str]:
        if self.config.player_cmd:
            return self.config.player_cmd.format(file=str(path)).split()

        audio_format = self.config.audio_format.strip().lower()
        if shutil.which("paplay") and audio_format in {"wav", "wave", "flac", "ogg", "oga"}:
            return ["paplay", str(path)]
        if shutil.which("ffplay"):
            return ["ffplay", "-nodisp", "-autoexit", "-loglevel", "error", str(path)]
        if shutil.which("aplay") and audio_format in {"wav", "wave"}:
            return ["aplay", "-q", str(path)]
        raise RuntimeError("no supported audio player found; install paplay, ffplay, or aplay")


class SpeakHandler(BaseHTTPRequestHandler):
    server_version = "MimoTtsBridge/0.1"

    def do_GET(self) -> None:
        if self.path != "/health":
            self._send_json(404, {"ok": False, "error": "not found"})
            return
        bridge = self._bridge()
        self._send_json(
            200,
            {
                "ok": True,
                "enabled": bridge.config.enabled,
                "queued": bridge.items.qsize(),
                "model": bridge.config.model,
            },
        )

    def do_POST(self) -> None:
        if self.path != "/speak":
            self._send_json(404, {"ok": False, "error": "not found"})
            return
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 8192:
            self._send_json(413, {"ok": False, "error": "invalid request size"})
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except json.JSONDecodeError:
            self._send_json(400, {"ok": False, "error": "invalid json"})
            return

        text = str(payload.get("text", "")).strip()
        if not text:
            self._send_json(422, {"ok": False, "error": "text is required"})
            return
        queued = self._bridge().enqueue(payload)
        self._send_json(202, {"ok": True, "queued": queued})

    def log_message(self, format: str, *args: Any) -> None:
        LOGGER.info("%s - %s", self.address_string(), format % args)

    def _bridge(self) -> MimoTtsBridge:
        bridge = getattr(self.server, "bridge", None)
        if bridge is None:
            raise RuntimeError("bridge not attached to HTTP server")
        return bridge

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Host-side MiMo TTS bridge for the car agent")
    parser.add_argument(
        "--env-file",
        default="agent-runtime/.env",
        help="env file to load before reading TTS settings",
    )
    parser.add_argument("--host", help="override TTS_BRIDGE_HOST")
    parser.add_argument("--port", type=int, help="override TTS_BRIDGE_PORT")
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = parse_args()
    load_env_file(Path(args.env_file))
    config = BridgeConfig()
    if args.host:
        config.host = args.host
    if args.port:
        config.port = args.port

    bridge = MimoTtsBridge(config)
    bridge.start()
    server = ThreadingHTTPServer((config.host, config.port), SpeakHandler)
    server.bridge = bridge  # type: ignore[attr-defined]
    LOGGER.info("MiMo TTS bridge listening on http://%s:%s", config.host, config.port)
    server.serve_forever()


if __name__ == "__main__":
    main()
