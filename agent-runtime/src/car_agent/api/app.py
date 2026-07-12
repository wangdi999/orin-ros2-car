from __future__ import annotations

import asyncio
import sqlite3
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from car_agent.api.events import EventHub
from car_agent.clients.llm_client import MockPlanProvider, OpenAICompatiblePlanProvider
from car_agent.clients.ros_gateway import InMemoryRobotGateway
from car_agent.config import Settings, get_settings
from car_agent.graph.builder import GraphServices, build_patrol_graph
from car_agent.models.api import (
    AgentRequest,
    ApprovalRequest,
    EmergencyStopRequest,
    TaskControlRequest,
)
from car_agent.repositories.database import Database
from car_agent.services.plan_validator import PlanValidator


def _interrupt_value(result: dict[str, Any]) -> Any | None:
    interrupts = result.get("__interrupt__") or []
    if not interrupts:
        return None
    first = interrupts[0]
    return getattr(first, "value", first)


def _graph_response(thread_id: str, result: dict[str, Any]) -> dict[str, Any]:
    interrupt_value = _interrupt_value(result)
    if interrupt_value:
        return {
            "thread_id": thread_id,
            "status": (
                "AWAITING_APPROVAL"
                if interrupt_value.get("type") == "PATROL_APPROVAL"
                else "WAITING_ROBOT_EVENT"
            ),
            "interrupt": interrupt_value,
            "task_id": result.get("task_id"),
            "task_state": result.get("task_state"),
        }
    return {
        "thread_id": thread_id,
        "status": result.get("task_state", "COMPLETED"),
        "task_id": result.get("task_id"),
        "task_state": result.get("task_state"),
        "error_code": result.get("error_code"),
        "error_message": result.get("error_message"),
        "response": result.get("final_response"),
        "validation_errors": result.get("validation_errors", []),
    }


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    database = Database(settings.database_path)
    database.sync_locations_from_yaml(settings.locations_path)
    gateway = InMemoryRobotGateway()
    if settings.gateway_mode != "mock":
        raise RuntimeError(
            "rosbridge gateway is intentionally disabled until the real car "
            "service contract is confirmed"
        )

    if settings.llm_provider == "openai_compatible":
        plan_provider = OpenAICompatiblePlanProvider(
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            api_key=settings.llm_api_key,
            timeout_sec=settings.llm_timeout_sec,
        )
    else:
        plan_provider = MockPlanProvider()

    checkpoint_connection = sqlite3.connect(
        settings.checkpoint_path,
        check_same_thread=False,
    )
    checkpointer = SqliteSaver(checkpoint_connection)
    graph = build_patrol_graph(
        GraphServices(
            database=database,
            gateway=gateway,
            plan_provider=plan_provider,
            validator=PlanValidator(),
        ),
        checkpointer,
    )
    events = EventHub()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        try:
            yield
        finally:
            database.close()
            checkpoint_connection.close()

    app = FastAPI(
        title="Orin Inspection Car Agent API",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )

    app.state.settings = settings
    app.state.database = database
    app.state.gateway = gateway
    app.state.graph = graph
    app.state.events = events

    def active_graph():
        graph = app.state.graph
        if graph is None:
            raise HTTPException(status_code=503, detail="agent graph is not initialized")
        return graph

    async def authorize(authorization: str | None = Header(default=None)) -> None:
        expected = f"Bearer {settings.agent_token}"
        if authorization != expected:
            raise HTTPException(status_code=401, detail="invalid bearer token")

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "ok": True,
            "gateway_mode": settings.gateway_mode,
            "llm_provider": settings.llm_provider,
        }

    @app.get("/api/v1/locations", dependencies=[Depends(authorize)])
    async def list_locations() -> dict[str, Any]:
        return {"items": [item.model_dump() for item in database.list_locations()]}

    @app.get("/api/v1/robot/status", dependencies=[Depends(authorize)])
    async def robot_status() -> dict[str, Any]:
        return (await gateway.get_robot_summary()).model_dump()

    @app.post("/api/v1/agent/requests", dependencies=[Depends(authorize)])
    async def create_agent_request(body: AgentRequest) -> dict[str, Any]:
        thread_id = str(uuid4())
        graph_input = {
                "thread_id": thread_id,
                "user_id": body.user_id,
                "user_request": body.text,
                "processed_event_ids": [],
                "alarms": [],
            }
        graph_config = {"configurable": {"thread_id": thread_id}}
        result = await asyncio.to_thread(
            active_graph().invoke,
            graph_input,
            graph_config,
        )
        response = _graph_response(thread_id, result)
        event_type = (
            "APPROVAL_REQUIRED"
            if response["status"] == "AWAITING_APPROVAL"
            else "AGENT_STATE_CHANGED"
        )
        await events.broadcast(
            event_type,
            response,
            task_id=response.get("task_id"),
            thread_id=thread_id,
        )
        return response

    @app.post("/api/v1/agent/threads/{thread_id}/resume", dependencies=[Depends(authorize)])
    async def resume_agent_thread(thread_id: str, body: ApprovalRequest) -> dict[str, Any]:
        result = await asyncio.to_thread(
            active_graph().invoke,
            Command(resume=body.model_dump()),
            {"configurable": {"thread_id": thread_id}},
        )
        response = _graph_response(thread_id, result)
        database.add_audit(
            operator=body.operator,
            action=f"AGENT_{body.decision}",
            target_id=response.get("task_id") or thread_id,
            request=body.model_dump(),
            result=response["status"],
            error_code=response.get("error_code"),
        )
        await events.broadcast(
            "TASK_STATE_CHANGED",
            response,
            task_id=response.get("task_id"),
            thread_id=thread_id,
        )
        return response

    @app.post("/api/v1/agent/threads/{thread_id}/events", dependencies=[Depends(authorize)])
    async def resume_agent_event(thread_id: str, body: dict[str, Any]) -> dict[str, Any]:
        if not body.get("event_id") or not body.get("event_type"):
            raise HTTPException(status_code=422, detail="event_id and event_type are required")
        result = await asyncio.to_thread(
            active_graph().invoke,
            Command(resume=body),
            {"configurable": {"thread_id": thread_id}},
        )
        response = _graph_response(thread_id, result)
        await events.broadcast(
            "TASK_STATE_CHANGED",
            response,
            task_id=response.get("task_id"),
            thread_id=thread_id,
        )
        return response

    @app.get("/api/v1/agent/threads/{thread_id}", dependencies=[Depends(authorize)])
    async def get_agent_thread(thread_id: str) -> dict[str, Any]:
        snapshot = await asyncio.to_thread(
            active_graph().get_state,
            {"configurable": {"thread_id": thread_id}},
        )
        if not snapshot.values:
            raise HTTPException(status_code=404, detail="thread not found")
        return {
            "thread_id": thread_id,
            "values": snapshot.values,
            "next": list(snapshot.next),
            "created_at": snapshot.created_at,
        }

    @app.get("/api/v1/tasks/current", dependencies=[Depends(authorize)])
    async def current_task() -> dict[str, Any]:
        return {"task": database.get_current_task()}

    @app.get("/api/v1/tasks/{task_id}", dependencies=[Depends(authorize)])
    async def get_task(task_id: str) -> dict[str, Any]:
        task = database.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="task not found")
        return task

    async def control_task(
        task_id: str,
        operation: str,
        body: TaskControlRequest,
    ) -> dict[str, Any]:
        result = await gateway.control_patrol(task_id, operation, body.reason)
        if not result.get("success"):
            raise HTTPException(status_code=409, detail=result)
        database.update_task_state(task_id, result["state"])
        database.add_audit(
            operator=body.operator,
            action=f"TASK_{operation}",
            target_id=task_id,
            request=body.model_dump(),
            result=result["state"],
        )
        await events.broadcast("TASK_STATE_CHANGED", result, task_id=task_id)
        return result

    @app.post("/api/v1/tasks/{task_id}/pause", dependencies=[Depends(authorize)])
    async def pause_task(task_id: str, body: TaskControlRequest) -> dict[str, Any]:
        return await control_task(task_id, "PAUSE", body)

    @app.post("/api/v1/tasks/{task_id}/resume", dependencies=[Depends(authorize)])
    async def resume_task(task_id: str, body: TaskControlRequest) -> dict[str, Any]:
        return await control_task(task_id, "RESUME", body)

    @app.post("/api/v1/tasks/{task_id}/cancel", dependencies=[Depends(authorize)])
    async def cancel_task(task_id: str, body: TaskControlRequest) -> dict[str, Any]:
        return await control_task(task_id, "CANCEL", body)

    @app.post("/api/v1/safety/emergency-stop", dependencies=[Depends(authorize)])
    async def emergency_stop(body: EmergencyStopRequest) -> dict[str, Any]:
        result = await gateway.set_emergency_stop(body.active, body.reason)
        database.add_audit(
            operator=body.operator,
            action="EMERGENCY_STOP" if body.active else "EMERGENCY_STOP_CLEAR",
            target_id=None,
            request=body.model_dump(),
            result="SUCCESS" if result.get("success") else "FAILED",
        )
        await events.broadcast("SAFETY_STOPPED" if body.active else "SAFETY_CLEARED", result)
        return result

    @app.websocket("/api/v1/events")
    async def websocket_events(websocket: WebSocket) -> None:
        if websocket.headers.get("authorization") != f"Bearer {settings.agent_token}":
            await websocket.close(code=4401)
            return
        await events.connect(websocket)
        try:
            summary = await gateway.get_robot_summary()
            await websocket.send_json(
                {
                    "event_id": str(uuid4()),
                    "type": "ROBOT_SNAPSHOT",
                    "data": summary.model_dump(),
                }
            )
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            await events.disconnect(websocket)

    return app
