from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from car_agent.models.motion import MotionIntent


class AgentRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    user_id: str = Field(default="admin", min_length=1, max_length=100)


class MotionParseRequest(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    user_id: str = Field(default="admin", min_length=1, max_length=100)


class MotionExecuteRequest(BaseModel):
    intent: MotionIntent
    confirmed: bool = False
    operator: str = Field(default="admin", min_length=1, max_length=100)
    source_text: str = Field(default="", max_length=500)


class SpeechTranscriptionRequest(BaseModel):
    audio_base64: str = Field(min_length=1)
    audio_format: str = Field(default="webm", min_length=1, max_length=30)
    language: str | None = Field(default="zh-CN", max_length=20)
    user_id: str = Field(default="admin", min_length=1, max_length=100)


class ApprovalRequest(BaseModel):
    decision: Literal["APPROVE", "REJECT", "EDIT"]
    operator: str = Field(default="admin", min_length=1, max_length=100)
    comment: str = Field(default="", max_length=1000)
    edited_plan: dict | None = None


class TaskControlRequest(BaseModel):
    reason: str = Field(default="", max_length=1000)
    operator: str = Field(default="admin", min_length=1, max_length=100)


class EmergencyStopRequest(BaseModel):
    active: bool = True
    reason: str = Field(default="Emergency stop requested", max_length=1000)
    operator: str = Field(default="admin", min_length=1, max_length=100)
