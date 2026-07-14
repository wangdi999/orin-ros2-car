from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from car_agent.api.app import create_app
from car_agent.clients.motion_intent import parse_motion_intent_heuristic
from car_agent.config import Settings


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
    )


def test_heuristic_motion_parser_accepts_short_forward_move() -> None:
    result = parse_motion_intent_heuristic("小车向前移动10厘米")

    assert result.ok is True
    assert result.intent.action == "MOVE"
    assert result.intent.direction == "FORWARD"
    assert result.intent.distance_m == 0.10
    assert result.intent.max_speed_mps == 0.05
    assert result.requires_confirmation is True


def test_heuristic_motion_parser_rejects_turns() -> None:
    result = parse_motion_intent_heuristic("原地左转90度")

    assert result.ok is False
    assert result.executable is False
    assert result.intent.action == "REJECT"


def test_motion_parse_api_uses_safe_parser(tmp_path: Path) -> None:
    headers = {"Authorization": "Bearer test-token"}

    with TestClient(create_app(_settings(tmp_path))) as client:
        response = client.post(
            "/api/v1/agent/motion/parse",
            headers=headers,
            json={"text": "后退5厘米", "user_id": "tester"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["intent"]["action"] == "MOVE"
    assert payload["intent"]["direction"] == "BACKWARD"
    assert payload["intent"]["distance_m"] == 0.05


def test_speech_transcribe_requires_asr_enabled(tmp_path: Path) -> None:
    headers = {"Authorization": "Bearer test-token"}

    with TestClient(create_app(_settings(tmp_path))) as client:
        response = client.post(
            "/api/v1/agent/speech/transcribe",
            headers=headers,
            json={"audio_base64": "AAAA", "audio_format": "webm"},
        )

    assert response.status_code == 503
