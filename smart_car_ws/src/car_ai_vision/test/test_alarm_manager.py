"""报警消抖状态机单元测试。"""

from unittest.mock import patch

from car_ai_vision.alarm_manager import (
    COOLDOWN_CONFIG,
    AlarmDebouncer,
    AlarmState,
)


class TestAlarmDebouncer:
    def test_first_detection_publishes(self):
        debouncer = AlarmDebouncer()
        assert debouncer.should_publish("person_detected") is True
        assert debouncer.get_state("person_detected") == AlarmState.DETECTED

    def test_second_call_enters_cooldown(self):
        debouncer = AlarmDebouncer()
        with patch("car_ai_vision.alarm_manager.time.time", return_value=1000.0):
            debouncer.should_publish("person_detected")
            assert debouncer.should_publish("person_detected") is False
            assert debouncer.get_state("person_detected") == AlarmState.COOLDOWN
            remaining = debouncer.get_cooldown_remaining("person_detected")
            assert remaining == COOLDOWN_CONFIG["person_detected"]

    def test_abnormal_behavior_has_shorter_cooldown(self):
        debouncer = AlarmDebouncer()
        with patch("car_ai_vision.alarm_manager.time.time", return_value=500.0):
            debouncer.should_publish("abnormal_behavior")
            debouncer.should_publish("abnormal_behavior")
            remaining = debouncer.get_cooldown_remaining("abnormal_behavior")
            assert remaining == 10.0

    def test_cooldown_expiry_moves_to_recovery_then_idle(self):
        debouncer = AlarmDebouncer()
        start = 1000.0
        cooldown = COOLDOWN_CONFIG["abnormal_behavior"]

        with patch("car_ai_vision.alarm_manager.time.time", return_value=start):
            debouncer.should_publish("abnormal_behavior")
            debouncer.should_publish("abnormal_behavior")

        with patch(
            "car_ai_vision.alarm_manager.time.time",
            return_value=start + cooldown,
        ):
            assert debouncer.should_publish("abnormal_behavior") is False
            assert debouncer.get_state("abnormal_behavior") == AlarmState.RECOVERY

        with patch(
            "car_ai_vision.alarm_manager.time.time",
            return_value=start + cooldown + 2.1,
        ):
            assert debouncer.should_publish("abnormal_behavior") is False
            assert debouncer.get_state("abnormal_behavior") == AlarmState.IDLE

    def test_danger_types_are_independent(self):
        debouncer = AlarmDebouncer()
        with patch("car_ai_vision.alarm_manager.time.time", return_value=0.0):
            assert debouncer.should_publish("person_detected") is True
            assert debouncer.should_publish("abnormal_behavior") is True

    def test_reset_returns_to_idle(self):
        debouncer = AlarmDebouncer()
        with patch("car_ai_vision.alarm_manager.time.time", return_value=0.0):
            debouncer.should_publish("person_detected")
            debouncer.should_publish("person_detected")
        debouncer.reset("person_detected")
        assert debouncer.get_state("person_detected") == AlarmState.IDLE
        assert debouncer.get_cooldown_remaining("person_detected") == 0.0

    def test_unknown_danger_type_gets_default_cooldown(self):
        debouncer = AlarmDebouncer()
        with patch("car_ai_vision.alarm_manager.time.time", return_value=100.0):
            assert debouncer.should_publish("custom_event") is True
            debouncer.should_publish("custom_event")
            assert debouncer.get_cooldown_remaining("custom_event") == 30.0
