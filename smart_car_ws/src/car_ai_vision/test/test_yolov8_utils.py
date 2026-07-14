"""
YOLOv8 推理节点工具函数单元测试。

测试 yolov8_inference.py 中的纯函数（离线可测）：
  - validate_confidence
  - validate_danger_type
  - validate_coordinate
  - make_iso8601_utc
"""

import sys
import os
import math
import re
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# 在导入 yolov8_inference 之前 mock 所有 ROS2 依赖
# 使用 unittest.mock.MagicMock 创建完整的包层次结构
from unittest.mock import MagicMock

_ros_modules = {
    "rclpy": None,
    "rclpy.node": None,
    "rclpy.qos": None,
    "rclpy.parameter": None,
    "sensor_msgs": None,
    "sensor_msgs.msg": None,
    "nav_msgs": None,
    "nav_msgs.msg": None,
    "tf2_msgs": None,
    "tf2_msgs.msg": None,
    "geometry_msgs": None,
    "geometry_msgs.msg": None,
    "cv_bridge": None,
    "car_ai_interfaces": None,
    "car_ai_interfaces.msg": None,
    "ultralytics": None,
}

for _mod in _ros_modules:
    if _mod not in sys.modules:
        _mock = MagicMock()
        sys.modules[_mod] = _mock

from car_ai_vision.yolov8_inference import (
    validate_confidence,
    validate_danger_type,
    validate_coordinate,
    make_iso8601_utc,
    VALID_DANGER_TYPES,
)


class TestValidateConfidence:
    """validate_confidence 函数测试。"""

    def test_valid_confidence(self):
        """有效置信度应返回 True。"""
        assert validate_confidence(0.0) is True
        assert validate_confidence(0.5) is True
        assert validate_confidence(1.0) is True
        assert validate_confidence(0.85) is True

    def test_none_confidence(self):
        """None 应返回 False。"""
        assert validate_confidence(None) is False

    def test_out_of_range_confidence(self):
        """超出 [0,1] 应返回 False。"""
        assert validate_confidence(-0.1) is False
        assert validate_confidence(1.1) is False
        assert validate_confidence(100.0) is False

    def test_nan_confidence(self):
        """NaN 应返回 False。"""
        assert validate_confidence(float("nan")) is False

    def test_inf_confidence(self):
        """Inf 应返回 False。"""
        assert validate_confidence(float("inf")) is False
        assert validate_confidence(float("-inf")) is False


class TestValidateDangerType:
    """validate_danger_type 函数测试。"""

    def test_valid_danger_types(self):
        """所有有效 danger_type 应返回 True。"""
        for dt in VALID_DANGER_TYPES:
            assert validate_danger_type(dt) is True

    def test_invalid_danger_type(self):
        """无效 danger_type 应返回 False。"""
        assert validate_danger_type("") is False
        assert validate_danger_type("unknown_type") is False
        assert validate_danger_type("ABNORMAL_BEHAVIOR") is False  # 区分大小写
        assert validate_danger_type("person") is False
        assert validate_danger_type("fire") is False

    def test_none_danger_type(self):
        """None 应返回 False。"""
        assert validate_danger_type(None) is False

    def test_danger_type_covers_cooldown_config(self):
        """VALID_DANGER_TYPES 应与 COOLDOWN_CONFIG 的键一致。"""
        from car_ai_vision.alarm_manager import COOLDOWN_CONFIG
        cooldown_keys = set(COOLDOWN_CONFIG.keys())
        assert VALID_DANGER_TYPES == cooldown_keys, (
            f"不一致: VALID_DANGER_TYPES={VALID_DANGER_TYPES} "
            f"vs COOLDOWN_CONFIG keys={cooldown_keys}"
        )


class TestValidateCoordinate:
    """validate_coordinate 函数测试。"""

    def test_valid_coordinates(self):
        """有效有限坐标应返回 True。"""
        assert validate_coordinate(0.0, 0.0) is True
        assert validate_coordinate(10.5, -3.2) is True
        assert validate_coordinate(-100.0, 50.0) is True

    def test_none_coordinates(self):
        """None 坐标应返回 False。"""
        assert validate_coordinate(None, 0.0) is False
        assert validate_coordinate(0.0, None) is False
        assert validate_coordinate(None, None) is False

    def test_nan_coordinates(self):
        """NaN 坐标应返回 False。"""
        assert validate_coordinate(float("nan"), 0.0) is False
        assert validate_coordinate(0.0, float("nan")) is False
        assert validate_coordinate(float("nan"), float("nan")) is False

    def test_inf_coordinates(self):
        """Inf 坐标应返回 False。"""
        assert validate_coordinate(float("inf"), 0.0) is False
        assert validate_coordinate(0.0, float("-inf")) is False
        assert validate_coordinate(float("inf"), float("inf")) is False


class TestMakeIso8601Utc:
    """make_iso8601_utc 函数测试。"""

    def test_returns_string(self):
        """应返回字符串。"""
        ts = make_iso8601_utc()
        assert isinstance(ts, str)

    def test_format(self):
        """应返回 ISO 8601 UTC 格式。"""
        ts = make_iso8601_utc()
        # 格式: YYYY-MM-DDTHH:MM:SSZ
        pattern = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"
        assert re.match(pattern, ts), f"不符合 ISO 8601 格式: {ts}"

    def test_ends_with_z(self):
        """应以 Z 结尾表示 UTC。"""
        ts = make_iso8601_utc()
        assert ts.endswith("Z")

    def test_two_calls_different(self):
        """连续两次调用可能返回不同值（取决于时间）。"""
        ts1 = make_iso8601_utc()
        ts2 = make_iso8601_utc()
        # 两者应为有效格式（可能相同如果时间精度不够）
        assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", ts1)
        assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", ts2)
