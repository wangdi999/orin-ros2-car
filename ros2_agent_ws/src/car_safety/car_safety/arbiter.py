from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Velocity:
    linear_x: float = 0.0
    linear_y: float = 0.0
    angular_z: float = 0.0


@dataclass(frozen=True)
class Limits:
    max_linear_x: float = 0.10
    max_linear_y: float = 0.10
    max_angular_z: float = 0.30


def sanitize(value: Velocity, limits: Limits) -> Velocity | None:
    values = (value.linear_x, value.linear_y, value.angular_z)
    if not all(math.isfinite(item) for item in values):
        return None
    return Velocity(
        linear_x=max(-limits.max_linear_x, min(limits.max_linear_x, value.linear_x)),
        linear_y=max(-limits.max_linear_y, min(limits.max_linear_y, value.linear_y)),
        angular_z=max(-limits.max_angular_z, min(limits.max_angular_z, value.angular_z)),
    )


def choose_velocity(
    *,
    emergency_stopped: bool,
    now_ms: int,
    teleop: Velocity,
    teleop_at_ms: int | None,
    teleop_timeout_ms: int,
    navigation: Velocity,
    navigation_at_ms: int | None,
    navigation_timeout_ms: int,
    patrol_running: bool,
) -> tuple[str, Velocity]:
    if emergency_stopped:
        return "EMERGENCY_STOP", Velocity()
    if teleop_at_ms is not None and now_ms - teleop_at_ms <= teleop_timeout_ms:
        return "MANUAL_TELEOP", teleop
    if (
        patrol_running
        and navigation_at_ms is not None
        and now_ms - navigation_at_ms <= navigation_timeout_ms
    ):
        return "NAVIGATION", navigation
    return "ZERO", Velocity()
