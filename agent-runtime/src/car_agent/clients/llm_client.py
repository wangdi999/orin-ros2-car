from __future__ import annotations

import json
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
        return PatrolPlan.model_validate_json(content)
