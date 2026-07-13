from pathlib import Path

from fastapi.testclient import TestClient

from car_agent.api.app import create_app
from car_agent.config import Settings


def test_approval_and_robot_event_resume_workflow(tmp_path: Path) -> None:
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
    settings = Settings(
        CAR_AGENT_TOKEN="test-token",
        CAR_AGENT_DATABASE_PATH=tmp_path / "agent.db",
        CAR_AGENT_CHECKPOINT_PATH=tmp_path / "checkpoints.db",
        CAR_AGENT_LOCATIONS_PATH=locations,
        CAR_AGENT_GATEWAY_MODE="mock",
        LLM_PROVIDER="mock",
    )
    headers = {"Authorization": "Bearer test-token"}

    with TestClient(create_app(settings)) as client:
        created = client.post(
            "/api/v1/agent/requests",
            headers=headers,
            json={
                "text": "巡检东门，发现积水时暂停，最后返回起点",
                "user_id": "tester",
            },
        )
        assert created.status_code == 200
        assert created.json()["status"] == "AWAITING_APPROVAL"

        thread_id = created.json()["thread_id"]
        resumed = client.post(
            f"/api/v1/agent/threads/{thread_id}/resume",
            headers=headers,
            json={"decision": "APPROVE", "operator": "tester"},
        )
        assert resumed.status_code == 200
        assert resumed.json()["status"] == "WAITING_ROBOT_EVENT"

        task_id = resumed.json()["task_id"]
        current = client.get("/api/v1/tasks/current", headers=headers)
        assert current.json()["task"]["state"] == "RUNNING"

        completed = client.post(
            f"/api/v1/agent/threads/{thread_id}/events",
            headers=headers,
            json={"event_id": "evt-1", "event_type": "TASK_SUCCEEDED"},
        )
        assert completed.status_code == 200
        assert completed.json()["status"] == "SUCCEEDED"
        task = client.get(f"/api/v1/tasks/{task_id}", headers=headers).json()
        assert task["state"] == "SUCCEEDED"
