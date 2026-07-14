from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from car_agent.api.app import create_app
from car_agent.clients.motion_intent import MotionLimits, parse_motion_intent_heuristic
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


def test_heuristic_motion_parser_reads_configured_speed_and_duration() -> None:
    limits = MotionLimits(max_distance_m=1.0, max_speed_mps=0.1, max_duration_sec=10.0)

    result = parse_motion_intent_heuristic(
        "请让小车以每秒0.1米的速度向前行驶10秒",
        limits=limits,
    )

    assert result.ok is True
    assert result.intent.direction == "FORWARD"
    assert result.intent.distance_m is None
    assert result.intent.max_speed_mps == 0.1
    assert result.intent.duration_sec == 10.0


def test_heuristic_motion_parser_keeps_default_limits() -> None:
    result = parse_motion_intent_heuristic("请让小车以每秒0.1米的速度向前行驶10秒")

    assert result.ok is False
    assert any("速度超过安全上限" in error for error in result.errors)
    assert any("持续时间超过安全上限" in error for error in result.errors)


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


def test_motion_execute_requires_confirmation(tmp_path: Path) -> None:
    headers = {"Authorization": "Bearer test-token"}

    with TestClient(create_app(_settings(tmp_path))) as client:
        response = client.post(
            "/api/v1/agent/motion/execute",
            headers=headers,
            json={
                "intent": {
                    "action": "MOVE",
                    "direction": "FORWARD",
                    "distance_m": 0.10,
                    "max_speed_mps": 0.05,
                },
                "confirmed": False,
                "operator": "tester",
                "source_text": "前进10厘米",
            },
        )

    assert response.status_code == 409


def test_motion_execute_calls_gateway_after_confirmation(tmp_path: Path) -> None:
    headers = {"Authorization": "Bearer test-token"}

    with TestClient(create_app(_settings(tmp_path))) as client:
        response = client.post(
            "/api/v1/agent/motion/execute",
            headers=headers,
            json={
                "intent": {
                    "action": "MOVE",
                    "direction": "FORWARD",
                    "distance_m": 0.10,
                    "max_speed_mps": 0.05,
                },
                "confirmed": True,
                "operator": "tester",
                "source_text": "前进10厘米",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["gateway_result"]["accepted"] is True
    assert payload["gateway_result"]["mock"] is True


def test_speech_transcribe_requires_asr_enabled(tmp_path: Path) -> None:
    headers = {"Authorization": "Bearer test-token"}

    with TestClient(create_app(_settings(tmp_path))) as client:
        response = client.post(
            "/api/v1/agent/speech/transcribe",
            headers=headers,
            json={"audio_base64": "AAAA", "audio_format": "webm"},
        )

    assert response.status_code == 503
