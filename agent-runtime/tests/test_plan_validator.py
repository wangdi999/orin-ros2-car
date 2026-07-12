from car_agent.models.plan import Location, PatrolPlan, RobotSummary
from car_agent.services.plan_validator import PlanValidator


def ready_robot(**overrides) -> RobotSummary:
    values = {
        "gateway_online": True,
        "chassis_online": True,
        "nav2_ready": True,
        "emergency_stopped": False,
        "active_task_state": "IDLE",
    }
    values.update(overrides)
    return RobotSummary(**values)


LOCATIONS = [
    Location(location_id="home", display_name="起点", x=0, y=0, yaw=0, enabled=True),
    Location(location_id="east_gate", display_name="东门", x=1, y=0, yaw=0, enabled=True),
]


def test_valid_plan_is_accepted() -> None:
    plan = PatrolPlan(
        name="东门巡检",
        waypoints=["east_gate"],
        event_policy={"flooding": "pause_and_notify"},
        return_home=True,
    )
    result = PlanValidator().validate(plan, locations=LOCATIONS, robot=ready_robot())
    assert result.valid is True
    assert result.errors == []


def test_unknown_location_is_rejected() -> None:
    plan = PatrolPlan(name="非法地点", waypoints=["unknown"])
    result = PlanValidator().validate(plan, locations=LOCATIONS, robot=ready_robot())
    assert result.valid is False
    assert "UNKNOWN_LOCATION:unknown" in result.errors


def test_emergency_stop_and_task_conflict_are_rejected() -> None:
    plan = PatrolPlan(name="测试", waypoints=["east_gate"])
    robot = ready_robot(
        emergency_stopped=True,
        active_task_id="task-running",
        active_task_state="RUNNING",
    )
    result = PlanValidator().validate(plan, locations=LOCATIONS, robot=robot)
    assert "ROBOT_ESTOPPED" in result.errors
    assert "TASK_ALREADY_RUNNING" in result.errors
