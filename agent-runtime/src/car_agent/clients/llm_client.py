from __future__ import annotations

import json
import re
from typing import Protocol

import httpx

from car_agent.models.plan import Location, PatrolPlan, RobotSummary


class PlanProvider(Protocol):
    async def generate_plan(
        self,
        *,
        user_request: str,
        allowed_locations: list[Location],
        robot_summary: RobotSummary,
    ) -> PatrolPlan: ...


class MockPlanProvider:
    """Deterministic parser for development and offline contract tests.

    It deliberately refuses to invent locations. A location is selected only when
    its ID or display name occurs in the user's text.
    """

    async def generate_plan(
        self,
        *,
        user_request: str,
        allowed_locations: list[Location],
        robot_summary: RobotSummary,
    ) -> PatrolPlan:
        del robot_summary
        text = user_request.lower()
        selected = [
            location.location_id
            for location in allowed_locations
            if location.enabled
            and (location.location_id.lower() in text or location.display_name.lower() in text)
        ]
        if not selected:
            raise ValueError("NO_KNOWN_LOCATION_IN_REQUEST")

        event_policy: dict[str, str] = {}
        if "积水" in user_request or "flooding" in text:
            event_policy["flooding"] = (
                "pause_and_notify" if "暂停" in user_request else "record_and_notify"
            )
        if "障碍" in user_request or "obstacle" in text:
            event_policy["obstacle"] = "record_and_notify"
        if "坑洼" in user_request or "pothole" in text:
            event_policy["pothole"] = "record_and_notify"

        return PatrolPlan(
            name="自然语言巡检任务",
            waypoints=selected,
            event_policy=event_policy,
            return_home=("返回起点" in user_request or "回到起点" in user_request),
            summary=user_request,
        )


class OpenAICompatiblePlanProvider:
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str,
        timeout_sec: float,
    ) -> None:
        if not base_url or not model or not api_key:
            raise ValueError("LLM configuration is incomplete")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout_sec = timeout_sec

    async def generate_plan(
        self,
        *,
        user_request: str,
        allowed_locations: list[Location],
        robot_summary: RobotSummary,
    ) -> PatrolPlan:
        allowed = [
            {
                "location_id": item.location_id,
                "display_name": item.display_name,
                "enabled": item.enabled,
                "description": item.description,
            }
            for item in allowed_locations
        ]
        prompt = {
            "request": user_request,
            "allowed_locations": allowed,
            "robot_summary": robot_summary.model_dump(),
            "constraints": {
                "max_waypoints": 10,
                "allowed_event_actions": [
                    "record",
                    "record_and_notify",
                    "pause_and_notify",
                ],
                "forbidden_fields": [
                    "x",
                    "y",
                    "yaw",
                    "speed",
                    "topic",
                    "shell",
                    "code",
                ],
            },
        }
        body = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Generate one JSON patrol plan. Only use enabled location_id values "
                        "provided by the caller. Never output coordinates, velocities, ROS topics, "
                        "shell commands, or code."
                    ),
                },
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0,
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        async with httpx.AsyncClient(timeout=self.timeout_sec) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                json=body,
                headers=headers,
            )
            response.raise_for_status()
        payload = response.json()
        content = payload["choices"][0]["message"]["content"]
        return PatrolPlan.model_validate(
            _normalize_plan_payload(
                content,
                user_request=user_request,
            )
        )


def _normalize_plan_payload(content: str, *, user_request: str) -> dict:
    payload = json.loads(_strip_json_fence(content))
    if not isinstance(payload, dict):
        raise ValueError("LLM plan response must be a JSON object")

    waypoints = payload.get("waypoints", [])
    if isinstance(waypoints, list):
        waypoints = [_waypoint_id(item) for item in waypoints]
        waypoints = [item for item in waypoints if item]
    else:
        waypoints = []

    if not waypoints:
        for key in ("location_id", "start_location_id", "target_location_id"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                waypoints.append(value)
                break

    return_home = payload.get("return_home", False)
    if not isinstance(return_home, bool):
        return_home = str(return_home).strip().lower() in {"true", "yes", "1", "是", "返回"}
    start_location = payload.get("start_location_id")
    end_location = payload.get("end_location_id")
    if isinstance(start_location, str) and start_location and start_location == end_location:
        return_home = True
    if "返回起点" in user_request or "回到起点" in user_request:
        return_home = True

    event_policy = payload.get("event_policy", {})
    if not isinstance(event_policy, dict):
        event_policy = {}

    return {
        "name": _string_value(payload.get("name") or payload.get("task_name"), "自然语言巡检任务"),
        "waypoints": waypoints,
        "event_policy": event_policy,
        "return_home": return_home,
        "summary": _string_value(
            payload.get("summary") or payload.get("task_summary"),
            user_request,
        ),
    }


def _strip_json_fence(content: str) -> str:
    text = content.strip()
    match = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else text


def _waypoint_id(item: object) -> str | None:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        for key in ("location_id", "id", "name"):
            value = item.get(key)
            if isinstance(value, str) and value:
                return value
    return None


def _string_value(value: object, fallback: str) -> str:
    return value if isinstance(value, str) and value.strip() else fallback
