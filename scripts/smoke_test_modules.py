"""无 pytest 依赖的本地冒烟验证脚本。"""

import sys
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "smart_car_ws" / "src" / "car_ai_vision"))
sys.path.insert(0, str(ROOT / "ros2_agent_ws" / "src" / "car_safety"))
sys.path.insert(0, str(ROOT / "ros2_agent_ws" / "src" / "car_patrol"))

from car_ai_vision.abnormal_behavior import AbnormalBehaviorDetector
from car_ai_vision.alarm_manager import AlarmDebouncer, AlarmState, COOLDOWN_CONFIG
from car_safety.arbiter import Limits, Velocity, choose_velocity, sanitize


def check_abnormal_behavior() -> None:
    detector = AbnormalBehaviorDetector(consecutive_frames=3)
    fallen = (100, 200, 300, 280)
    standing = (100, 100, 160, 280)
    for _ in range(5):
        assert detector.update([standing], None)[0] is False
    for i in range(3):
        result = detector.update([fallen], None)[0]
    assert result is False
    assert detector.update([fallen], None)[0] is True


def check_alarm_manager() -> None:
    debouncer = AlarmDebouncer()
    with patch("car_ai_vision.alarm_manager.time.time", return_value=1000.0):
        assert debouncer.should_publish("person_detected") is True
        assert debouncer.should_publish("person_detected") is False
        assert debouncer.get_state("person_detected") == AlarmState.COOLDOWN
    assert COOLDOWN_CONFIG["abnormal_behavior"] == 10


def check_safety_arbiter() -> None:
    source, velocity = choose_velocity(
        emergency_stopped=True,
        now_ms=1000,
        teleop=Velocity(0.35, 0.0, 1.2),
        teleop_at_ms=999,
        teleop_timeout_ms=450,
        navigation=Velocity(),
        navigation_at_ms=None,
        navigation_timeout_ms=500,
        patrol_running=False,
    )
    assert source == "EMERGENCY_STOP"
    assert velocity == Velocity()
    limits = Limits(0.10, 0.10, 0.30)
    assert sanitize(Velocity(0.35, 0.35, 1.2), limits) == Velocity(0.10, 0.10, 0.30)


def main() -> int:
    checks = [
        ("abnormal_behavior", check_abnormal_behavior),
        ("alarm_manager", check_alarm_manager),
        ("safety_arbiter", check_safety_arbiter),
    ]
    for name, fn in checks:
        fn()
        print(f"OK  {name}")
    print("All smoke checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
