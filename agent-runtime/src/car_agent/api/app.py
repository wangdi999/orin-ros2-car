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
from car_agent.clients.asr_client import MimoSpeechRecognizer
from car_agent.clients.llm_client import MockPlanProvider, OpenAICompatiblePlanProvider
from car_agent.clients.motion_intent import (
    HeuristicMotionIntentProvider,
    MotionLimits,
    OpenAICompatibleMotionIntentProvider,
    parse_motion_intent_heuristic,
    validate_motion_intent,
)
from car_agent.clients.ros_gateway import HttpRobotGateway, InMemoryRobotGateway, RobotGatewayError
from car_agent.clients.tts_client import TtsNotifier
from car_agent.config import Settings, get_settings
from car_agent.features.alarm_reports import register_alarm_report_routes
from car_agent.graph.builder import GraphServices, build_patrol_graph
from car_agent.models.api import (
    AgentRequest,
    ApprovalRequest,
    EmergencyStopRequest,
    MotionExecuteRequest,
    MotionParseRequest,
    SpeechTranscriptionRequest,
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


def _robot_event_announcement(event_type: str) -> str | None:
    announcements = {
        "TASK_SUCCEEDED": "巡检任务已完成。",
        "TASK_FAILED": "巡检任务失败，请查看控制台。",
        "TASK_CANCELLED": "巡检任务已取消。",
        "TASK_PAUSED": "巡检任务已暂停。",
        "TASK_RESUMED": "巡检任务已继续。",
    }
    return announcements.get(event_type)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    motion_limits = MotionLimits(
        max_distance_m=settings.motion_max_distance_m,
        max_speed_mps=settings.motion_max_speed_mps,
        max_duration_sec=settings.motion_max_duration_sec,
    )
    database = Database(settings.database_path)
    database.sync_locations_from_yaml(settings.locations_path)
    if settings.gateway_mode == "mock":
        gateway = InMemoryRobotGateway()
    elif settings.gateway_mode == "http_rosbridge":
        gateway = HttpRobotGateway(
            base_url=settings.ros_gateway_base_url,
            timeout_sec=settings.ros_gateway_timeout_sec,
        )
    else:
        raise RuntimeError(
            "CAR_AGENT_GATEWAY_MODE=rosbridge is reserved; use http_rosbridge "
            "with the host-side ROS gateway bridge"
        )

    if settings.llm_provider == "openai_compatible":
        plan_provider = OpenAICompatiblePlanProvider(
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            api_key=settings.llm_api_key,
            timeout_sec=settings.llm_timeout_sec,
        )
        motion_intent_provider = OpenAICompatibleMotionIntentProvider(
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            api_key=settings.llm_api_key,
            timeout_sec=settings.llm_timeout_sec,
            limits=motion_limits,
        )
    else:
        plan_provider = MockPlanProvider()
        motion_intent_provider = HeuristicMotionIntentProvider(limits=motion_limits)

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
    tts_notifier = TtsNotifier(
        enabled=settings.tts_enabled,
        bridge_url=settings.tts_bridge_url,
        timeout_sec=settings.tts_timeout_sec,
    )
    speech_recognizer = None
    speech_recognizer_error = ""
    if settings.asr_enabled:
        try:
            speech_recognizer = MimoSpeechRecognizer(
                base_url=settings.asr_base_url or settings.llm_base_url,
                model=settings.asr_model,
                api_key=settings.asr_api_key or settings.llm_api_key,
                timeout_sec=settings.asr_timeout_sec,
            )
        except ValueError as exc:
            speech_recognizer_error = str(exc)

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
    app.state.tts_notifier = tts_notifier
    app.state.motion_intent_provider = motion_intent_provider
    app.state.motion_limits = motion_limits
    app.state.speech_recognizer = speech_recognizer
    app.state.speech_recognizer_error = speech_recognizer_error

    def announce(
        text: str,
        *,
        event: str,
        priority: str = "normal",
        task_id: str | None = None,
        thread_id: str | None = None,
    ) -> None:
        notifier = getattr(app.state, "tts_notifier", None)
        if notifier is None:
            return
        notifier.notify(
            text,
            event=event,
            priority=priority,
            task_id=task_id,
            thread_id=thread_id,
        )

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
            "tts_enabled": settings.tts_enabled,
            "asr_enabled": settings.asr_enabled,
            "asr_configured": speech_recognizer is not None,
            "asr_model": settings.asr_model if settings.asr_enabled else "",
            "motion_limits": motion_limits.as_dict(),
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
        announce(
            "已收到巡检指令，正在生成计划。",
            event="AGENT_REQUEST_RECEIVED",
            thread_id=thread_id,
        )
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
        if response["status"] == "AWAITING_APPROVAL":
            announce(
                "巡检计划已生成，请确认。",
                event="APPROVAL_REQUIRED",
                task_id=response.get("task_id"),
                thread_id=thread_id,
            )
        elif response.get("error_code"):
            announce(
                "巡检指令处理失败，请查看控制台。",
                event="AGENT_REQUEST_FAILED",
                priority="high",
                task_id=response.get("task_id"),
                thread_id=thread_id,
            )
        return response

    @app.post("/api/v1/agent/motion/parse", dependencies=[Depends(authorize)])
    async def parse_motion_request(body: MotionParseRequest) -> dict[str, Any]:
        provider = app.state.motion_intent_provider
        try:
            result = await provider.parse_motion_intent(body.text)
        except Exception as exc:
            result = parse_motion_intent_heuristic(body.text, limits=app.state.motion_limits)
            result.warnings.append(f"LLM 解析失败，已使用本地兜底解析：{exc}")
        database.add_audit(
            operator=body.user_id,
            action="MOTION_PARSE",
            target_id=None,
            request=body.model_dump(),
            result="ACCEPTED" if result.ok else "REJECTED",
            error_code=None if result.ok else "MOTION_PARSE_REJECTED",
        )
        return result.model_dump()

    @app.post("/api/v1/agent/motion/execute", dependencies=[Depends(authorize)])
    async def execute_motion_request(body: MotionExecuteRequest) -> dict[str, Any]:
        validation = validate_motion_intent(
            body.intent.model_copy(deep=True),
            text=body.source_text or body.intent.reason or "motion execute",
            source="llm",
            limits=app.state.motion_limits,
        )
        if not validation.ok or not validation.executable:
            database.add_audit(
                operator=body.operator,
                action="MOTION_EXECUTE_REJECTED",
                target_id=None,
                request=body.model_dump(),
                result="REJECTED",
                error_code="INVALID_MOTION_INTENT",
            )
            raise HTTPException(status_code=422, detail=validation.model_dump())
        if validation.requires_confirmation and not body.confirmed:
            raise HTTPException(status_code=409, detail="motion execution requires confirmation")
        try:
            result = await gateway.execute_motion(validation.intent)
        except RobotGatewayError as exc:
            database.add_audit(
                operator=body.operator,
                action="MOTION_EXECUTE",
                target_id=None,
                request=body.model_dump(),
                result="REJECTED",
                error_code=str(exc.payload.get("error_code") or "MOTION_GATEWAY_REJECTED"),
            )
            raise HTTPException(status_code=exc.status_code, detail=exc.payload) from exc
        except Exception as exc:
            database.add_audit(
                operator=body.operator,
                action="MOTION_EXECUTE",
                target_id=None,
                request=body.model_dump(),
                result="FAILED",
                error_code="MOTION_GATEWAY_FAILED",
            )
            raise HTTPException(status_code=502, detail=f"motion gateway failed: {exc}") from exc
        if result.get("accepted") is False or result.get("success") is False:
            database.add_audit(
                operator=body.operator,
                action="MOTION_EXECUTE",
                target_id=None,
                request=body.model_dump(),
                result="REJECTED",
                error_code=str(result.get("error_code") or "MOTION_REJECTED"),
            )
            raise HTTPException(status_code=409, detail=result)
        database.add_audit(
            operator=body.operator,
            action="MOTION_EXECUTE",
            target_id=None,
            request=body.model_dump(),
            result=str(result.get("state") or "ACCEPTED"),
        )
        payload = {
            "ok": True,
            "intent": validation.intent.model_dump(),
            "gateway_result": result,
            "warnings": validation.warnings,
        }
        await events.broadcast("MOTION_EXECUTED", payload)
        if validation.intent.action == "MOVE":
            announce(
                "已执行低速短距离运动指令。",
                event="MOTION_EXECUTED",
            )
        elif validation.intent.action == "STOP":
            announce("已发送停车指令。", event="MOTION_STOPPED")
        elif validation.intent.action == "EMERGENCY_STOP":
            announce("急停已开启。", event="MOTION_EMERGENCY_STOPPED", priority="high")
        return payload

    @app.post("/api/v1/agent/speech/transcribe", dependencies=[Depends(authorize)])
    async def transcribe_speech(body: SpeechTranscriptionRequest) -> dict[str, Any]:
        recognizer = app.state.speech_recognizer
        if recognizer is None:
            detail = app.state.speech_recognizer_error or "ASR is not enabled"
            raise HTTPException(status_code=503, detail=detail)
        try:
            result = await recognizer.transcribe(
                audio_base64=body.audio_base64,
                audio_format=body.audio_format,
                language=body.language,
            )
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"ASR transcription failed: {exc}") from exc
        database.add_audit(
            operator=body.user_id,
            action="SPEECH_TRANSCRIBE",
            target_id=None,
            request={
                "audio_format": body.audio_format,
                "language": body.language,
                "audio_base64_chars": len(body.audio_base64),
            },
            result="SUCCESS" if result.ok else "EMPTY",
        )
        return result.model_dump()

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
        decision = body.decision.upper()
        if decision == "APPROVE":
            if response.get("error_code"):
                announce(
                    "任务启动失败，请查看控制台。",
                    event="TASK_START_FAILED",
                    priority="high",
                    task_id=response.get("task_id"),
                    thread_id=thread_id,
                )
            else:
                announce(
                    "任务已批准，开始执行巡检。",
                    event="TASK_APPROVED",
                    task_id=response.get("task_id"),
                    thread_id=thread_id,
                )
        elif decision == "REJECT":
            announce(
                "任务已拒绝。",
                event="TASK_REJECTED",
                task_id=response.get("task_id"),
                thread_id=thread_id,
            )
        elif decision == "EDIT":
            announce(
                "巡检计划已更新，请再次确认。",
                event="TASK_EDITED",
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
        announcement = _robot_event_announcement(str(body.get("event_type", "")))
        if announcement:
            announce(
                announcement,
                event=str(body.get("event_type", "")),
                priority="high" if body.get("event_type") == "TASK_FAILED" else "normal",
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
        control_announcements = {
            "PAUSE": "任务已暂停。",
            "RESUME": "任务已继续。",
            "CANCEL": "任务已取消。",
        }
        announce(
            control_announcements.get(operation, "任务状态已更新。"),
            event=f"TASK_{operation}",
            task_id=task_id,
        )
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
        announce(
            "急停已开启。" if body.active else "急停已解除。",
            event="SAFETY_STOPPED" if body.active else "SAFETY_CLEARED",
            priority="high",
        )
        return result

    register_alarm_report_routes(app, settings, authorize, events, database)

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
