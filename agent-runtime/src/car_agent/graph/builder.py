from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Literal
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from car_agent.clients.llm_client import PlanProvider
from car_agent.clients.ros_gateway import RobotGateway
from car_agent.graph.state import AgentState
from car_agent.models.plan import Location, PatrolPlan, RobotSummary
from car_agent.repositories.database import Database
from car_agent.services.plan_validator import PlanValidator


@dataclass(slots=True)
class GraphServices:
    database: Database
    gateway: RobotGateway
    plan_provider: PlanProvider
    validator: PlanValidator


def build_patrol_graph(services: GraphServices, checkpointer: Any):
    def run_async(awaitable):
        return asyncio.run(awaitable)

    def classify_intent(state: AgentState) -> dict:
        request = state.get("user_request", "")
        intent = "CREATE_PATROL" if request.strip() else "UNKNOWN"
        return {"intent": intent}

    def load_context(state: AgentState) -> dict:
        del state
        robot = run_async(services.gateway.get_robot_summary())
        locations = services.database.list_locations()
        return {
            "robot_summary": robot.model_dump(),
            "allowed_locations": [item.model_dump() for item in locations],
        }

    def generate_plan(state: AgentState) -> dict:
        try:
            plan = run_async(
                services.plan_provider.generate_plan(
                    user_request=state["user_request"],
                    allowed_locations=[
                        Location.model_validate(item) for item in state["allowed_locations"]
                    ],
                    robot_summary=RobotSummary.model_validate(state["robot_summary"]),
                )
            )
            return {"plan": plan.model_dump(), "llm_status": "OK"}
        except Exception as exc:  # provider errors are converted into a stable graph state
            return {
                "llm_status": "DEGRADED",
                "error_code": "PLAN_GENERATION_FAILED",
                "error_message": str(exc),
            }

    def validate_plan(state: AgentState) -> dict:
        if not state.get("plan"):
            return {
                "validation_errors": [state.get("error_code", "PLAN_MISSING")],
                "validation_warnings": [],
            }
        plan = PatrolPlan.model_validate(state["plan"])
        result = services.validator.validate(
            plan,
            locations=[Location.model_validate(item) for item in state["allowed_locations"]],
            robot=RobotSummary.model_validate(state["robot_summary"]),
        )
        return {
            "validation_errors": result.errors,
            "validation_warnings": result.warnings,
        }

    def route_after_validation(state: AgentState) -> Literal["request_approval", "failed"]:
        return "failed" if state.get("validation_errors") else "request_approval"

    def failed(state: AgentState) -> dict:
        return {
            "task_state": "REJECTED",
            "final_response": "任务未通过本地校验",
            "error_code": state.get("error_code") or "PLAN_VALIDATION_FAILED",
        }

    def request_approval(state: AgentState) -> dict:
        response = interrupt(
            {
                "type": "PATROL_APPROVAL",
                "thread_id": state["thread_id"],
                "plan": state["plan"],
                "robot_summary": state["robot_summary"],
                "warnings": state.get("validation_warnings", []),
            }
        )
        decision = str(response.get("decision", "REJECT")).upper()
        update: dict[str, Any] = {"approval": response}
        if decision == "EDIT":
            edited = response.get("edited_plan")
            if not edited:
                return {
                    **update,
                    "task_state": "REJECTED",
                    "error_code": "EDITED_PLAN_MISSING",
                }
            update["plan"] = PatrolPlan.model_validate(edited).model_dump()
        elif decision == "REJECT":
            update.update(
                {
                    "task_state": "CANCELLED",
                    "final_response": "任务已被管理员拒绝",
                }
            )
        return update

    def route_after_approval(state: AgentState) -> Literal["submit_task", "validate_plan", "done"]:
        decision = str(state.get("approval", {}).get("decision", "REJECT")).upper()
        if decision == "APPROVE":
            return "submit_task"
        if decision == "EDIT":
            return "validate_plan"
        return "done"

    def submit_task(state: AgentState) -> dict:
        plan = PatrolPlan.model_validate(state["plan"])
        task_id = state.get("task_id") or str(uuid4())
        existing = services.database.get_task(task_id)
        if existing is None:
            services.database.create_task(
                task_id=task_id,
                thread_id=state["thread_id"],
                plan=plan,
                created_by=state.get("user_id", "unknown"),
                state="READY",
            )
        create_result = run_async(services.gateway.create_patrol(task_id, plan))
        if not create_result.get("accepted"):
            error_code = create_result.get("error_code", "PATROL_CREATE_REJECTED")
            services.database.update_task_state(task_id, "FAILED", error_code=error_code)
            return {
                "task_id": task_id,
                "task_state": "FAILED",
                "error_code": error_code,
            }
        start_result = run_async(services.gateway.control_patrol(task_id, "START"))
        if not start_result.get("success"):
            error_code = start_result.get("error_code", "PATROL_START_REJECTED")
            services.database.update_task_state(task_id, "FAILED", error_code=error_code)
            return {
                "task_id": task_id,
                "task_state": "FAILED",
                "error_code": error_code,
            }
        services.database.update_task_state(task_id, "RUNNING")
        return {"task_id": task_id, "task_state": "RUNNING"}

    def wait_robot_event(state: AgentState) -> dict:
        event = interrupt(
            {
                "type": "WAIT_ROBOT_EVENT",
                "thread_id": state["thread_id"],
                "task_id": state.get("task_id"),
            }
        )
        return {"pending_event": event}

    def handle_robot_event(state: AgentState) -> dict:
        event = state.get("pending_event", {})
        event_id = str(event.get("event_id", ""))
        processed = list(state.get("processed_event_ids", []))
        if event_id and event_id in processed:
            return {"pending_event": {}}
        if event_id:
            processed.append(event_id)

        event_type = str(event.get("event_type", ""))
        task_id = state.get("task_id")
        updates: dict[str, Any] = {"processed_event_ids": processed, "pending_event": {}}
        terminal = {
            "TASK_SUCCEEDED": "SUCCEEDED",
            "TASK_FAILED": "FAILED",
            "TASK_CANCELLED": "CANCELLED",
        }
        if event_type in terminal and task_id:
            final_state = terminal[event_type]
            services.database.update_task_state(task_id, final_state)
            updates.update(
                {
                    "task_state": final_state,
                    "final_response": f"巡检任务已结束：{final_state}",
                }
            )
        elif event_type == "TASK_PAUSED" and task_id:
            services.database.update_task_state(task_id, "PAUSED")
            updates["task_state"] = "PAUSED"
        elif event_type == "TASK_RESUMED" and task_id:
            services.database.update_task_state(task_id, "RUNNING")
            updates["task_state"] = "RUNNING"
        return updates

    def route_after_event(state: AgentState) -> Literal["done", "wait_robot_event"]:
        return (
            "done"
            if state.get("task_state") in {"SUCCEEDED", "FAILED", "CANCELLED"}
            else "wait_robot_event"
        )

    def done(state: AgentState) -> dict:
        return {"final_response": state.get("final_response", "工作流结束")}

    builder = StateGraph(AgentState)
    builder.add_node("classify_intent", classify_intent)
    builder.add_node("load_context", load_context)
    builder.add_node("generate_plan", generate_plan)
    builder.add_node("validate_plan", validate_plan)
    builder.add_node("failed", failed)
    builder.add_node("request_approval", request_approval)
    builder.add_node("submit_task", submit_task)
    builder.add_node("wait_robot_event", wait_robot_event)
    builder.add_node("handle_robot_event", handle_robot_event)
    builder.add_node("done", done)

    builder.add_edge(START, "classify_intent")
    builder.add_edge("classify_intent", "load_context")
    builder.add_edge("load_context", "generate_plan")
    builder.add_edge("generate_plan", "validate_plan")
    builder.add_conditional_edges(
        "validate_plan",
        route_after_validation,
        {"request_approval": "request_approval", "failed": "failed"},
    )
    builder.add_edge("failed", END)
    builder.add_conditional_edges(
        "request_approval",
        route_after_approval,
        {"submit_task": "submit_task", "validate_plan": "validate_plan", "done": "done"},
    )
    builder.add_edge("submit_task", "wait_robot_event")
    builder.add_edge("wait_robot_event", "handle_robot_event")
    builder.add_conditional_edges(
        "handle_robot_event",
        route_after_event,
        {"done": "done", "wait_robot_event": "wait_robot_event"},
    )
    builder.add_edge("done", END)
    return builder.compile(checkpointer=checkpointer)
