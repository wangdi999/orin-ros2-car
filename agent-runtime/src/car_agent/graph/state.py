from __future__ import annotations

from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    thread_id: str
    user_id: str
    user_request: str
    intent: str

    robot_summary: dict[str, Any]
    allowed_locations: list[dict[str, Any]]

    plan: dict[str, Any]
    validation_errors: list[str]
    validation_warnings: list[str]
    approval: dict[str, Any]

    task_id: str
    task_state: str
    current_waypoint: int

    pending_event: dict[str, Any]
    processed_event_ids: list[str]
    alarms: list[dict[str, Any]]

    llm_status: str
    final_response: str
    error_code: str
    error_message: str
