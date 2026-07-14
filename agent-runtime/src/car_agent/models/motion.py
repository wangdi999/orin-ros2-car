from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

MotionAction = Literal["MOVE", "STOP", "EMERGENCY_STOP", "REJECT"]
MotionDirection = Literal["FORWARD", "BACKWARD", "LEFT", "RIGHT"]


class MotionIntent(BaseModel):
    action: MotionAction
    direction: MotionDirection | None = None
    distance_m: float | None = Field(default=None, ge=0)
    max_speed_mps: float | None = Field(default=None, ge=0)
    duration_sec: float | None = Field(default=None, ge=0)
    reason: str = Field(default="", max_length=300)


class MotionParseResult(BaseModel):
    ok: bool
    intent: MotionIntent
    normalized_text: str
    executable: bool
    requires_confirmation: bool
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    source: Literal["llm", "heuristic"]


class SpeechTranscriptionResult(BaseModel):
    ok: bool
    text: str
    language: str | None = None
    duration_sec: float | None = None
    model: str
