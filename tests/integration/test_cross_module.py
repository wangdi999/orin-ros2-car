"""
跨模块联调测试。

验证 AI 视觉、控制台、Agent 编排等模块之间的共享契约与数据流一致性。
可在无 ROS2 / 无 GPU 环境下离线运行。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SMART_CAR_WS = REPO_ROOT / "smart_car_ws"
ROS2_AGENT_WS = REPO_ROOT / "ros2_agent_ws"
AGENT_RUNTIME = REPO_ROOT / "agent-runtime"

sys.path.insert(0, str(SMART_CAR_WS / "src" / "car_ai_vision"))
sys.path.insert(0, str(ROS2_AGENT_WS / "src" / "car_safety"))
sys.path.insert(0, str(ROS2_AGENT_WS / "src" / "car_patrol"))

from car_ai_vision.abnormal_behavior import AbnormalBehaviorDetector  # noqa: E402
from car_ai_vision.alarm_manager import COOLDOWN_CONFIG, AlarmDebouncer  # noqa: E402
from car_safety.arbiter import Limits, Velocity, choose_velocity, sanitize  # noqa: E402


class TestSharedContracts:
    def test_alarm_msg_danger_types_match_cooldown_config(self) -> None:
        msg_path = SMART_CAR_WS / "src" / "car_ai_interfaces" / "msg" / "Alarm.msg"
        assert msg_path.is_file()
        declared = {"person_detected", "abnormal_behavior", "cracked_tile"}
        assert declared == set(COOLDOWN_CONFIG.keys())

    def test_location_ids_overlap_between_agent_and_patrol(self) -> None:
        import yaml

        patrol_cfg = yaml.safe_load(
            (ROS2_AGENT_WS / "src" / "car_patrol" / "config" / "locations.yaml").read_text(
                encoding="utf-8"
            )
        )
        agent_cfg = yaml.safe_load(
            (AGENT_RUNTIME / "config" / "locations.yaml").read_text(encoding="utf-8")
        )
        patrol_ids = {item["location_id"] for item in patrol_cfg["locations"]}
        agent_ids = {item["location_id"] for item in agent_cfg["locations"]}
        assert "home" in patrol_ids & agent_ids


class TestAiAlarmPipeline:
    """模拟 yolov8_inference 中 检测 → 异常判定 → 报警消抖 的联调链路。"""

    def test_person_then_abnormal_independent_alarms(self) -> None:
        debouncer = AlarmDebouncer()
        detector = AbnormalBehaviorDetector(consecutive_frames=3)

        standing = (100, 100, 160, 280)
        fallen = (100, 200, 300, 280)

        person_alarm = debouncer.should_publish("person_detected")
        assert person_alarm is True

        abnormal = False
        for _ in range(4):
            results = detector.update([fallen], None)
            abnormal = results[0]
        assert abnormal is True

        abnormal_alarm = debouncer.should_publish("abnormal_behavior")
        assert abnormal_alarm is True

        debouncer.should_publish("person_detected")
        debouncer.should_publish("abnormal_behavior")
        assert debouncer.should_publish("person_detected") is False
        assert debouncer.should_publish("abnormal_behavior") is False

    def test_standing_person_does_not_trigger_abnormal_alarm(self) -> None:
        detector = AbnormalBehaviorDetector(consecutive_frames=3)
        standing = (100, 100, 60, 180)
        for _ in range(10):
            results = detector.update([standing], None)
        assert results[0] is False


class TestDriveSafetyPipeline:
    """模拟 控制台 Twist → 安全仲裁 的联调链路。"""

    def test_emergency_stop_overrides_teleop_twist(self) -> None:
        teleop = Velocity(0.35, 0.0, 1.2)
        source, velocity = choose_velocity(
            emergency_stopped=True,
            now_ms=1000,
            teleop=teleop,
            teleop_at_ms=999,
            teleop_timeout_ms=450,
            navigation=Velocity(),
            navigation_at_ms=None,
            navigation_timeout_ms=500,
            patrol_running=False,
        )
        assert source == "EMERGENCY_STOP"
        assert velocity == Velocity()

    def test_safety_limits_clamp_console_output(self) -> None:
        console_twist = Velocity(0.35, 0.35, 1.2)
        car_limits = Limits(0.10, 0.10, 0.30)
        sanitized = sanitize(console_twist, car_limits)
        assert sanitized == Velocity(0.10, 0.10, 0.30)
