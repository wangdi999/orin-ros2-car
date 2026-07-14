from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


MAX_DISTANCE_M = 0.30
MAX_SPEED_MPS = 0.08
MAX_DURATION_SEC = 8.0


class MotionValidationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class MotionCommand:
    action: str
    direction: str | None = None
    linear_x: float = 0.0
    linear_y: float = 0.0
    angular_z: float = 0.0
    distance_m: float | None = None
    max_speed_mps: float | None = None
    duration_sec: float = 0.0
    reason: str = ""


def normalize_motion_payload(payload: dict[str, Any]) -> MotionCommand:
    raw = payload.get("intent") if isinstance(payload.get("intent"), dict) else payload
    if not isinstance(raw, dict):
        raise MotionValidationError("INVALID_MOTION_PAYLOAD", "motion payload must be an object")

    action = str(raw.get("action") or "").strip().upper()
    if action == "STOP":
        return MotionCommand(action="STOP", reason=str(raw.get("reason") or ""))
    if action == "EMERGENCY_STOP":
        return MotionCommand(action="EMERGENCY_STOP", reason=str(raw.get("reason") or ""))
    if action != "MOVE":
        raise MotionValidationError("UNSUPPORTED_MOTION_ACTION", "unsupported motion action")

    direction = str(raw.get("direction") or "").strip().upper()
    if direction not in {"FORWARD", "BACKWARD", "LEFT", "RIGHT"}:
        raise MotionValidationError("INVALID_MOTION_DIRECTION", "unsupported motion direction")

    speed = _optional_float(raw.get("max_speed_mps"), default=0.05)
    if speed is None or speed <= 0.0:
        raise MotionValidationError("INVALID_MOTION_SPEED", "speed must be positive")
    if speed > MAX_SPEED_MPS:
        raise MotionValidationError(
            "MOTION_SPEED_TOO_HIGH",
            f"speed exceeds {MAX_SPEED_MPS:.2f} m/s",
        )

    distance = _optional_float(raw.get("distance_m"), default=None)
    duration = _optional_float(raw.get("duration_sec"), default=None)
    if distance is None and duration is None:
        raise MotionValidationError("MOTION_DISTANCE_REQUIRED", "distance or duration is required")
    if distance is not None:
        if distance <= 0.0:
            raise MotionValidationError("INVALID_MOTION_DISTANCE", "distance must be positive")
        if distance > MAX_DISTANCE_M:
            raise MotionValidationError(
                "MOTION_DISTANCE_TOO_LONG",
                f"distance exceeds {MAX_DISTANCE_M:.2f} m",
            )
    if duration is not None:
        if duration <= 0.0:
            raise MotionValidationError("INVALID_MOTION_DURATION", "duration must be positive")
        if duration > MAX_DURATION_SEC:
            raise MotionValidationError(
                "MOTION_DURATION_TOO_LONG",
                f"duration exceeds {MAX_DURATION_SEC:.1f} s",
            )

    if distance is not None:
        distance_duration = distance / speed
        duration = min(duration, distance_duration) if duration is not None else distance_duration
    assert duration is not None
    if duration > MAX_DURATION_SEC:
        raise MotionValidationError(
            "MOTION_DURATION_TOO_LONG",
            f"computed duration exceeds {MAX_DURATION_SEC:.1f} s",
        )

    linear_x, linear_y = _direction_to_velocity(direction, speed)
    return MotionCommand(
        action="MOVE",
        direction=direction,
        linear_x=linear_x,
        linear_y=linear_y,
        angular_z=0.0,
        distance_m=distance,
        max_speed_mps=speed,
        duration_sec=duration,
        reason=str(raw.get("reason") or ""),
    )


def _optional_float(value: Any, *, default: float | None) -> float | None:
    if value is None or value == "":
        return default
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise MotionValidationError("INVALID_MOTION_NUMBER", "motion number is invalid") from exc
    if not math.isfinite(number):
        raise MotionValidationError("INVALID_MOTION_NUMBER", "motion number must be finite")
    return number


def _direction_to_velocity(direction: str, speed: float) -> tuple[float, float]:
    if direction == "FORWARD":
        return speed, 0.0
    if direction == "BACKWARD":
        return -speed, 0.0
    if direction == "LEFT":
        return 0.0, speed
    if direction == "RIGHT":
        return 0.0, -speed
    raise MotionValidationError("INVALID_MOTION_DIRECTION", "unsupported motion direction")
