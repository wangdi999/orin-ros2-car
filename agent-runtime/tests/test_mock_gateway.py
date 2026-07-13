import pytest

from car_agent.clients.ros_gateway import InMemoryRobotGateway
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
