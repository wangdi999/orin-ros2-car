from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol

from car_agent.models.plan import PatrolPlan, RobotSummary


class RobotGateway(Protocol):
    async def get_robot_summary(self) -> RobotSummary: ...

    async def create_patrol(self, task_id: str, plan: PatrolPlan) -> dict: ...

    async def control_patrol(self, task_id: str, operation: str, reason: str = "") -> dict: ...

    async def set_emergency_stop(self, active: bool, reason: str = "") -> dict: ...


@dataclass
class InMemoryRobotGateway:
    """Safe default used before the real rosbridge contract is confirmed on the car."""

    summary: RobotSummary = field(
        default_factory=lambda: RobotSummary(
            gateway_online=True,
            chassis_online=True,
            lidar_online=True,
            camera_online=True,
            nav2_ready=True,
            yolo_online=False,
            emergency_stopped=False,
            active_task_state="IDLE",
            last_update=datetime.now(timezone.utc).isoformat(),
        )
    )
    tasks: dict[str, PatrolPlan] = field(default_factory=dict)

    async def get_robot_summary(self) -> RobotSummary:
        self.summary.last_update = datetime.now(timezone.utc).isoformat()
        return self.summary.model_copy(deep=True)

    async def create_patrol(self, task_id: str, plan: PatrolPlan) -> dict:
        if task_id in self.tasks:
            return {"accepted": True, "state": self.summary.active_task_state, "idempotent": True}
        if self.summary.emergency_stopped:
            return {"accepted": False, "error_code": "ROBOT_ESTOPPED"}
        if self.summary.active_task_id:
            return {"accepted": False, "error_code": "TASK_ALREADY_RUNNING"}
        self.tasks[task_id] = plan
        self.summary.active_task_id = task_id
        self.summary.active_task_state = "READY"
        return {"accepted": True, "state": "READY", "idempotent": False}

    async def control_patrol(self, task_id: str, operation: str, reason: str = "") -> dict:
        if self.summary.active_task_id != task_id:
            return {"success": False, "error_code": "TASK_NOT_ACTIVE"}
        transitions = {
            ("READY", "START"): "RUNNING",
            ("RUNNING", "PAUSE"): "PAUSED",
            ("PAUSED", "RESUME"): "RUNNING",
            ("READY", "CANCEL"): "CANCELLED",
            ("RUNNING", "CANCEL"): "CANCELLED",
            ("PAUSED", "CANCEL"): "CANCELLED",
        }
        key = (self.summary.active_task_state, operation)
        if key not in transitions:
            return {"success": False, "error_code": "INVALID_STATE_TRANSITION"}
        state = transitions[key]
        self.summary.active_task_state = state
        if state == "CANCELLED":
            self.summary.active_task_id = None
        return {"success": True, "state": state, "reason": reason}

    async def set_emergency_stop(self, active: bool, reason: str = "") -> dict:
        self.summary.emergency_stopped = active
        if active and self.summary.active_task_state == "RUNNING":
            self.summary.active_task_state = "PAUSED"
        return {"success": True, "active": active, "reason": reason}
