import pytest

from car_agent.clients.ros_gateway import HttpRobotGateway, InMemoryRobotGateway
from car_agent.models.motion import MotionIntent
from car_agent.models.plan import PatrolPlan


@pytest.mark.asyncio
async def test_gateway_enforces_state_transitions() -> None:
    gateway = InMemoryRobotGateway()
    plan = PatrolPlan(name="测试", waypoints=["home"])

    created = await gateway.create_patrol("task-1", plan)
    assert created["accepted"] is True
    assert (await gateway.control_patrol("task-1", "START"))["state"] == "RUNNING"
    assert (await gateway.control_patrol("task-1", "PAUSE"))["state"] == "PAUSED"
    assert (await gateway.control_patrol("task-1", "RESUME"))["state"] == "RUNNING"
    assert (await gateway.control_patrol("task-1", "CANCEL"))["state"] == "CANCELLED"


@pytest.mark.asyncio
async def test_gateway_emergency_stop_blocks_new_task() -> None:
    gateway = InMemoryRobotGateway()
    await gateway.set_emergency_stop(True, "test")
    result = await gateway.create_patrol(
        "task-1",
        PatrolPlan(name="测试", waypoints=["home"]),
    )
    assert result == {"accepted": False, "error_code": "ROBOT_ESTOPPED"}


@pytest.mark.asyncio
async def test_http_gateway_maps_patrol_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    requests = []

    class FakeResponse:
        def __init__(self, payload: dict, status_code: int = 200) -> None:
            self._payload = payload
            self.status_code = status_code
            self.text = str(payload)

        @property
        def is_error(self) -> bool:
            return self.status_code >= 400

        def json(self) -> dict:
            return self._payload

    class FakeClient:
        def __init__(self, *, timeout: float) -> None:
            self.timeout = timeout

        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def request(self, method: str, url: str, *, json: dict | None = None) -> FakeResponse:
            requests.append(
                {
                    "method": method,
                    "url": url,
                    "json": json,
                    "timeout": self.timeout,
                }
            )
            if url.endswith("/robot/summary"):
                return FakeResponse({"gateway_online": True, "active_task_state": "IDLE"})
            if url.endswith("/patrol/create"):
                return FakeResponse({"accepted": True})
            if url.endswith("/patrol/control"):
                return FakeResponse({"success": True, "state": "RUNNING"})
            if url.endswith("/motion/execute"):
                return FakeResponse(
                    {
                        "accepted": True,
                        "state": "RUNNING",
                        "mock": True,
                        "intent": json["intent"] if json else {},
                    }
                )
            return FakeResponse({"success": True, "active": True})

    monkeypatch.setattr("car_agent.clients.ros_gateway.httpx.AsyncClient", FakeClient)
    gateway = HttpRobotGateway(base_url="http://127.0.0.1:8130/", timeout_sec=1.5)

    summary = await gateway.get_robot_summary()
    assert summary.gateway_online is True
    assert (
        await gateway.create_patrol(
            "task-1",
            PatrolPlan(
                name="测试",
                waypoints=["home"],
                event_policy={"flooding": "record_and_notify"},
                return_home=True,
            ),
        )
    ) == {"accepted": True}
    assert await gateway.control_patrol("task-1", "START", "approved") == {
        "success": True,
        "state": "RUNNING",
    }
    assert await gateway.set_emergency_stop(True, "test") == {"success": True, "active": True}
    assert await gateway.execute_motion(
        MotionIntent(action="MOVE", direction="FORWARD", distance_m=0.1, max_speed_mps=0.05)
    ) == {
        "accepted": True,
        "state": "RUNNING",
        "mock": True,
        "intent": {
            "action": "MOVE",
            "direction": "FORWARD",
            "distance_m": 0.1,
            "max_speed_mps": 0.05,
            "duration_sec": None,
            "reason": "",
        },
    }

    assert requests == [
        {
            "method": "GET",
            "url": "http://127.0.0.1:8130/api/v1/robot/summary",
            "json": None,
            "timeout": 1.5,
        },
        {
            "method": "POST",
            "url": "http://127.0.0.1:8130/api/v1/patrol/create",
            "json": {
                "task_id": "task-1",
                "name": "测试",
                "location_ids": ["home"],
                "event_policy": {"flooding": "record_and_notify"},
                "return_home": True,
            },
            "timeout": 1.5,
        },
        {
            "method": "POST",
            "url": "http://127.0.0.1:8130/api/v1/patrol/control",
            "json": {
                "task_id": "task-1",
                "operation": "START",
                "reason": "approved",
            },
            "timeout": 1.5,
        },
        {
            "method": "POST",
            "url": "http://127.0.0.1:8130/api/v1/safety/emergency-stop",
            "json": {
                "active": True,
                "reason": "test",
            },
            "timeout": 1.5,
        },
        {
            "method": "POST",
            "url": "http://127.0.0.1:8130/api/v1/motion/execute",
            "json": {
                "intent": {
                    "action": "MOVE",
                    "direction": "FORWARD",
                    "distance_m": 0.1,
                    "max_speed_mps": 0.05,
                    "duration_sec": None,
                    "reason": "",
                },
            },
            "timeout": 1.5,
        },
    ]
