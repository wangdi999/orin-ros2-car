from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol

import httpx

from car_agent.models.motion import MotionIntent
from car_agent.models.plan import PatrolPlan, RobotSummary


class RobotGatewayError(RuntimeError):
    def __init__(self, status_code: int, payload: dict) -> None:
        error_code = payload.get("error_code", "ROS_GATEWAY_ERROR")
        error_message = payload.get("error_message", str(payload))
        super().__init__(f"{error_code}: {error_message}")
        self.status_code = status_code
        self.payload = payload


class RobotGateway(Protocol):
    async def get_robot_summary(self) -> RobotSummary: ...

    async def create_patrol(self, task_id: str, plan: PatrolPlan) -> dict: ...

    async def control_patrol(self, task_id: str, operation: str, reason: str = "") -> dict: ...

    async def set_emergency_stop(self, active: bool, reason: str = "") -> dict: ...

    async def execute_motion(self, intent: MotionIntent) -> dict: ...


class HttpRobotGateway:
    def __init__(self, *, base_url: str, timeout_sec: float) -> None:
        if not base_url:
            raise ValueError("ROS gateway base URL is required")
        self.base_url = base_url.rstrip("/")
        self.timeout_sec = timeout_sec

    async def get_robot_summary(self) -> RobotSummary:
        payload = await self._request("GET", "/api/v1/robot/summary")
        return RobotSummary.model_validate(payload)

    async def create_patrol(self, task_id: str, plan: PatrolPlan) -> dict:
        payload = {
            "task_id": task_id,
            "name": plan.name,
            "location_ids": plan.waypoints,
            "event_policy": plan.event_policy,
            "return_home": plan.return_home,
        }
        return await self._request("POST", "/api/v1/patrol/create", json=payload)

    async def control_patrol(self, task_id: str, operation: str, reason: str = "") -> dict:
        payload = {
            "task_id": task_id,
            "operation": operation,
            "reason": reason,
        }
        return await self._request("POST", "/api/v1/patrol/control", json=payload)

    async def set_emergency_stop(self, active: bool, reason: str = "") -> dict:
        return await self._request(
            "POST",
            "/api/v1/safety/emergency-stop",
            json={"active": active, "reason": reason},
        )

    async def execute_motion(self, intent: MotionIntent) -> dict:
        return await self._request(
            "POST",
            "/api/v1/motion/execute",
            json={"intent": intent.model_dump()},
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict | None = None,
    ) -> dict:
        async with httpx.AsyncClient(timeout=self.timeout_sec) as client:
            response = await client.request(method, f"{self.base_url}{path}", json=json)
        try:
            payload = response.json()
        except ValueError:
            payload = {
                "error_code": "ROS_GATEWAY_INVALID_RESPONSE",
                "error_message": response.text,
            }
        if response.is_error:
            raise RobotGatewayError(response.status_code, payload)
        if not isinstance(payload, dict):
            raise RuntimeError("ROS gateway response must be a JSON object")
        return payload


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

    async def execute_motion(self, intent: MotionIntent) -> dict:
        if intent.action == "EMERGENCY_STOP":
            return await self.set_emergency_stop(True, intent.reason or "motion emergency stop")
        if intent.action == "STOP":
            return {"accepted": True, "state": "STOPPED", "mock": True}
        if self.summary.emergency_stopped:
            return {"accepted": False, "error_code": "ROBOT_ESTOPPED", "mock": True}
        return {
            "accepted": True,
            "state": "RUNNING",
            "mock": True,
            "intent": intent.model_dump(),
        }
