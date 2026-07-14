from pathlib import Path

from fastapi.testclient import TestClient

from car_agent.api.app import create_app
from car_agent.config import Settings


def test_app_uses_http_rosbridge_gateway(tmp_path: Path) -> None:
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
    settings = Settings(
        CAR_AGENT_TOKEN="test-token",
        CAR_AGENT_DATABASE_PATH=tmp_path / "agent.db",
        CAR_AGENT_CHECKPOINT_PATH=tmp_path / "checkpoints.db",
        CAR_AGENT_LOCATIONS_PATH=locations,
        CAR_AGENT_GATEWAY_MODE="http_rosbridge",
        ROS_GATEWAY_BASE_URL="http://127.0.0.1:8130",
        LLM_PROVIDER="mock",
    )

    with TestClient(create_app(settings)) as client:
        health = client.get("/health")

    assert health.status_code == 200
    assert health.json()["gateway_mode"] == "http_rosbridge"
