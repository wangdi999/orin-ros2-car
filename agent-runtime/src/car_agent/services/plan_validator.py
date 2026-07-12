from __future__ import annotations

from car_agent.models.plan import Location, PatrolPlan, PlanValidationResult, RobotSummary

ALLOWED_POLICIES = {"record", "record_and_notify", "pause_and_notify"}


class PlanValidator:
    def validate(
        self,
        plan: PatrolPlan,
        *,
        locations: list[Location],
        robot: RobotSummary,
    ) -> PlanValidationResult:
        errors: list[str] = []
        warnings: list[str] = []
        location_map = {location.location_id: location for location in locations}

        for location_id in plan.waypoints:
            location = location_map.get(location_id)
            if location is None:
                errors.append(f"UNKNOWN_LOCATION:{location_id}")
            elif not location.enabled:
                errors.append(f"LOCATION_DISABLED:{location_id}")

        for danger_type, action in plan.event_policy.items():
            if action not in ALLOWED_POLICIES:
                errors.append(f"INVALID_EVENT_POLICY:{danger_type}:{action}")

        if robot.emergency_stopped:
            errors.append("ROBOT_ESTOPPED")
        if not robot.gateway_online:
            errors.append("ROBOT_GATEWAY_OFFLINE")
        if not robot.chassis_online:
            errors.append("CHASSIS_OFFLINE")
        if not robot.nav2_ready:
            errors.append("NAV2_NOT_READY")
        if robot.active_task_id and robot.active_task_state not in {
            "IDLE",
            "SUCCEEDED",
            "FAILED",
            "CANCELLED",
        }:
            errors.append("TASK_ALREADY_RUNNING")

        if plan.return_home and "home" not in location_map:
            errors.append("HOME_LOCATION_MISSING")
        elif plan.return_home and not location_map["home"].enabled:
            errors.append("HOME_LOCATION_DISABLED")

        if not plan.event_policy:
            warnings.append("NO_EVENT_POLICY")

        return PlanValidationResult(valid=not errors, errors=errors, warnings=warnings)
