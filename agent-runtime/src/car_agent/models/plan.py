from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

EventAction = Literal["record", "record_and_notify", "pause_and_notify"]


class Location(BaseModel):
    model_config = ConfigDict(extra="forbid")

    location_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_\-]+$")
    display_name: str = Field(min_length=1, max_length=100)
    x: float
    y: float
    yaw: float
    enabled: bool = True
    description: str = ""
    priority: int = 0


class PatrolPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    waypoints: list[str] = Field(min_length=1, max_length=10)
    event_policy: dict[str, EventAction] = Field(default_factory=dict)
    return_home: bool = False
    summary: str = Field(default="", max_length=1000)

    @field_validator("waypoints")
    @classmethod
    def reject_duplicate_waypoints(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("waypoints must not contain duplicates")
        return value


class RobotSummary(BaseModel):
    gateway_online: bool = False
    chassis_online: bool = False
    lidar_online: bool = False
    camera_online: bool = False
    nav2_ready: bool = False
    yolo_online: bool = False
    emergency_stopped: bool = False
    active_task_id: str | None = None
    active_task_state: str = "IDLE"
    current_waypoint_index: int = 0
    current_location_id: str | None = None
    pose_x: float | None = None
    pose_y: float | None = None
    pose_yaw: float | None = None
    last_update: str | None = None


class PlanValidationResult(BaseModel):
    valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
