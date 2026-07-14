from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Protocol

import httpx
from pydantic import ValidationError

from car_agent.models.motion import MotionIntent, MotionParseResult


@dataclass(frozen=True)
class MotionLimits:
    max_distance_m: float = 0.30
    max_speed_mps: float = 0.08
    max_duration_sec: float = 8.0

    def as_dict(self) -> dict[str, float]:
        return {
            "max_distance_m": self.max_distance_m,
            "max_speed_mps": self.max_speed_mps,
            "max_duration_sec": self.max_duration_sec,
        }


DEFAULT_MOTION_LIMITS = MotionLimits()

_SPEED_PATTERNS = (
    re.compile(r"每\s*(?:秒|s)\s*([0-9]+(?:\.[0-9]+)?)\s*(?:米|m)", re.IGNORECASE),
    re.compile(
        r"([0-9]+(?:\.[0-9]+)?)\s*(?:米|m)\s*(?:每\s*(?:秒|s)|/\s*(?:秒|s))",
        re.IGNORECASE,
    ),
    re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*mps", re.IGNORECASE),
)


class MotionIntentProvider(Protocol):
    async def parse_motion_intent(self, text: str) -> MotionParseResult: ...


class HeuristicMotionIntentProvider:
    def __init__(self, *, limits: MotionLimits = DEFAULT_MOTION_LIMITS) -> None:
        self.limits = limits

    async def parse_motion_intent(self, text: str) -> MotionParseResult:
        return parse_motion_intent_heuristic(text, limits=self.limits)


class OpenAICompatibleMotionIntentProvider:
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str,
        timeout_sec: float,
        limits: MotionLimits = DEFAULT_MOTION_LIMITS,
    ) -> None:
        if not base_url or not model or not api_key:
            raise ValueError("LLM configuration is incomplete")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout_sec = timeout_sec
        self.limits = limits

    async def parse_motion_intent(self, text: str) -> MotionParseResult:
        body = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Parse one low-speed robot motion command into JSON only. "
                        "Allowed actions: MOVE, STOP, EMERGENCY_STOP, REJECT. "
                        "Allowed MOVE directions: FORWARD, BACKWARD, LEFT, RIGHT. "
                        "Never output ROS topics, code, shell commands, coordinates, "
                        "angular motion, or direct velocity control. Reject turns, patrols, "
                        "navigation goals, unknown directions, and unsafe requests."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "text": text,
                            "limits": self.limits.as_dict(),
                            "schema": {
                                "action": "MOVE|STOP|EMERGENCY_STOP|REJECT",
                                "direction": "FORWARD|BACKWARD|LEFT|RIGHT|null",
                                "distance_m": "number|null",
                                "max_speed_mps": "number|null",
                                "duration_sec": "number|null",
                                "reason": "short Chinese explanation",
                            },
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0,
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        async with httpx.AsyncClient(timeout=self.timeout_sec) as client:
            response = await client.post(
                chat_completions_url(self.base_url),
                json=body,
                headers=headers,
            )
            response.raise_for_status()
        payload = response.json()
        content = payload["choices"][0]["message"]["content"]
        intent = _intent_from_payload(content)
        return validate_motion_intent(intent, text=text, source="llm", limits=self.limits)


def parse_motion_intent_heuristic(
    text: str,
    *,
    limits: MotionLimits = DEFAULT_MOTION_LIMITS,
) -> MotionParseResult:
    normalized = _normalize_text(text)
    if not normalized:
        return _reject(text, "EMPTY_COMMAND", "请输入运动指令。", source="heuristic")

    if any(token in normalized for token in ("急停", "紧急停止", "立即停止", "刹车")):
        return validate_motion_intent(
            MotionIntent(action="EMERGENCY_STOP", reason="用户请求急停"),
            text=text,
            source="heuristic",
            limits=limits,
        )
    if any(token in normalized for token in ("停止", "停车", "停下", "stop")):
        return validate_motion_intent(
            MotionIntent(action="STOP", reason="用户请求停车"),
            text=text,
            source="heuristic",
            limits=limits,
        )
    if any(token in normalized for token in ("转", "旋转", "掉头", "角度", "导航", "巡检")):
        return _reject(
            text,
            "UNSUPPORTED_MOTION",
            "当前临时底盘桥只允许短距离直线或横移，不支持转向、导航或巡检。",
            source="heuristic",
        )

    direction = None
    if any(token in normalized for token in ("前进", "向前", "forward")):
        direction = "FORWARD"
    elif any(token in normalized for token in ("后退", "向后", "backward", "back")):
        direction = "BACKWARD"
    elif any(token in normalized for token in ("左移", "向左", "左平移")):
        direction = "LEFT"
    elif any(token in normalized for token in ("右移", "向右", "右平移")):
        direction = "RIGHT"

    if direction is None:
        return _reject(
            text,
            "UNKNOWN_DIRECTION",
            "无法识别安全运动方向，只支持前进、后退、左移、右移、停止和急停。",
            source="heuristic",
        )

    speed_mps = _extract_speed_mps(normalized)
    distance_m = _extract_distance_m(_remove_speed_expressions(normalized))
    duration_sec = _extract_duration_sec(normalized)
    if distance_m is None and duration_sec is None:
        distance_m = 0.10
    speed_mps = speed_mps if speed_mps is not None else min(limits.max_speed_mps, 0.05)
    return validate_motion_intent(
        MotionIntent(
            action="MOVE",
            direction=direction,
            distance_m=distance_m,
            max_speed_mps=speed_mps,
            duration_sec=duration_sec,
            reason="解析为低速短距离运动",
        ),
        text=text,
        source="heuristic",
        limits=limits,
    )


def validate_motion_intent(
    intent: MotionIntent,
    *,
    text: str,
    source: str,
    limits: MotionLimits = DEFAULT_MOTION_LIMITS,
) -> MotionParseResult:
    errors: list[str] = []
    warnings: list[str] = []
    normalized = text.strip()

    if intent.action == "REJECT":
        errors.append(intent.reason or "指令被拒绝。")
    elif intent.action == "MOVE":
        if intent.direction is None:
            errors.append("MOVE 指令必须包含方向。")
        if intent.distance_m is None and intent.duration_sec is None:
            errors.append("MOVE 指令必须包含距离或持续时间。")
        if intent.distance_m is not None and intent.distance_m > limits.max_distance_m:
            errors.append(f"距离超过安全上限 {limits.max_distance_m:.2f} m。")
        if intent.duration_sec is not None and intent.duration_sec > limits.max_duration_sec:
            errors.append(f"持续时间超过安全上限 {limits.max_duration_sec:.1f} s。")
        if intent.max_speed_mps is not None and intent.max_speed_mps > limits.max_speed_mps:
            errors.append(f"速度超过安全上限 {limits.max_speed_mps:.2f} m/s。")
        if intent.max_speed_mps is None:
            intent.max_speed_mps = min(limits.max_speed_mps, 0.05)
        if intent.max_speed_mps <= 0:
            errors.append("运动速度必须大于 0。")
        if intent.duration_sec is not None and intent.max_speed_mps > 0:
            implied_distance = intent.duration_sec * intent.max_speed_mps
            if intent.distance_m is not None:
                implied_distance = min(implied_distance, intent.distance_m)
            if implied_distance > limits.max_distance_m + 1e-9:
                errors.append(f"速度与时间对应的路程超过安全上限 {limits.max_distance_m:.2f} m。")
        warnings.append("执行前必须确认小车周围空旷或轮子悬空。")
        warnings.append("真实执行必须经 safety_supervisor 和 rosmaster_app_bridge。")
    elif intent.action == "STOP":
        warnings.append("停车指令仍应经安全层发送零速。")
    elif intent.action == "EMERGENCY_STOP":
        warnings.append("急停会锁定安全状态，恢复前需要人工解除。")

    executable = not errors and intent.action in {"MOVE", "STOP", "EMERGENCY_STOP"}
    return MotionParseResult(
        ok=not errors,
        intent=intent,
        normalized_text=normalized,
        executable=executable,
        requires_confirmation=intent.action == "MOVE" and executable,
        warnings=warnings,
        errors=errors,
        source="llm" if source == "llm" else "heuristic",
    )


def _intent_from_payload(content: str) -> MotionIntent:
    payload = json.loads(_strip_json_fence(content))
    if not isinstance(payload, dict):
        raise ValueError("motion intent response must be a JSON object")
    if isinstance(payload.get("intent"), dict):
        payload = payload["intent"]
    try:
        return MotionIntent.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(f"invalid motion intent response: {exc}") from exc


def _strip_json_fence(content: str) -> str:
    text = content.strip()
    match = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else text


def _normalize_text(text: str) -> str:
    return text.strip().lower().replace("　", " ")


def _extract_distance_m(text: str) -> float | None:
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(厘米|公分|cm|米|m)", text)
    if not match:
        return None
    value = float(match.group(1))
    unit = match.group(2)
    if unit in {"厘米", "公分", "cm"}:
        return value / 100.0
    return value


def _extract_duration_sec(text: str) -> float | None:
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(秒|s)", text)
    return float(match.group(1)) if match else None


def _extract_speed_mps(text: str) -> float | None:
    for pattern in _SPEED_PATTERNS:
        match = pattern.search(text)
        if match:
            return float(match.group(1))
    return None


def _remove_speed_expressions(text: str) -> str:
    for pattern in _SPEED_PATTERNS:
        text = pattern.sub(" ", text)
    return text


def _reject(text: str, code: str, reason: str, *, source: str) -> MotionParseResult:
    return MotionParseResult(
        ok=False,
        intent=MotionIntent(action="REJECT", reason=reason),
        normalized_text=text.strip(),
        executable=False,
        requires_confirmation=False,
        warnings=[],
        errors=[f"{code}: {reason}"],
        source="llm" if source == "llm" else "heuristic",
    )


def chat_completions_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    if base.endswith("/v1"):
        return f"{base}/chat/completions"
    return f"{base}/v1/chat/completions"
