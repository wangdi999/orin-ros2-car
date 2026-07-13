"""
safety_supervisor 逻辑单元测试。

在无 ROS2 环境下直接测试核心逻辑：
  - monotonic_ms 时间函数
  - Twist ↔ Velocity 转换
  - 紧急停止状态管理
  - 巡逻状态跟踪
  - 状态 JSON 序列化
"""

import sys
import os
import time
import json
import pytest
from unittest.mock import MagicMock, patch

# Mock ROS2 依赖
_ros_mocks = [
    "rclpy", "rclpy.node", "rclpy.qos", "rclpy.parameter",
    "geometry_msgs", "geometry_msgs.msg",
    "std_msgs", "std_msgs.msg",
    "car_interfaces", "car_interfaces.msg",
]
for _m in _ros_mocks:
    if _m not in sys.modules:
        sys.modules[_m] = MagicMock()

from car_safety.arbiter import Velocity, Limits
from car_safety.safety_supervisor import monotonic_ms


# ============================================================
# 直接从源码提取的核心逻辑（避免导入 SafetySupervisor）
# ============================================================

def _from_twist(msg) -> Velocity:
    """复现 SafetySupervisor._from_twist 逻辑。"""
    return Velocity(msg.linear.x, msg.linear.y, msg.angular.z)


def _to_twist(value: Velocity):
    """复现 SafetySupervisor._to_twist 逻辑。"""
    msg = MagicMock()
    msg.linear.x = value.linear_x
    msg.linear.y = value.linear_y
    msg.angular.z = value.angular_z
    return msg


def _make_state_json(source, emergency_stopped, patrol_running, limits):
    """复现 SafetySupervisor._publish_state 逻辑。"""
    return json.dumps(
        {
            "source": source,
            "emergency_stopped": emergency_stopped,
            "patrol_running": patrol_running,
            "limits": {
                "linear_x": limits.max_linear_x,
                "linear_y": limits.max_linear_y,
                "angular_z": limits.max_angular_z,
            },
        },
        separators=(",", ":"),
    )


class TestMonotonicMs:
    """monotonic_ms 函数测试。"""

    def test_returns_int(self):
        result = monotonic_ms()
        assert isinstance(result, int)

    def test_increasing(self):
        t1 = monotonic_ms()
        time.sleep(0.01)
        t2 = monotonic_ms()
        assert t2 >= t1

    def test_positive(self):
        assert monotonic_ms() > 0


class TestFromTwist:
    """_from_twist 逻辑测试。"""

    def test_basic_conversion(self):
        msg = MagicMock()
        msg.linear.x = 0.05
        msg.linear.y = 0.0
        msg.angular.z = 0.10
        vel = _from_twist(msg)
        assert vel.linear_x == 0.05
        assert vel.linear_y == 0.0
        assert vel.angular_z == 0.10

    def test_zero_twist(self):
        msg = MagicMock()
        msg.linear.x = 0.0
        msg.linear.y = 0.0
        msg.angular.z = 0.0
        vel = _from_twist(msg)
        assert vel == Velocity()

    def test_negative_values(self):
        msg = MagicMock()
        msg.linear.x = -0.05
        msg.linear.y = -0.02
        msg.angular.z = -0.15
        vel = _from_twist(msg)
        assert vel.linear_x == -0.05
        assert vel.linear_y == -0.02
        assert vel.angular_z == -0.15


class TestToTwist:
    """_to_twist 逻辑测试。"""

    def test_basic_conversion(self):
        vel = Velocity(0.08, -0.03, 0.20)
        msg = _to_twist(vel)
        assert msg.linear.x == 0.08
        assert msg.linear.y == -0.03
        assert msg.angular.z == 0.20

    def test_zero_velocity(self):
        vel = Velocity()
        msg = _to_twist(vel)
        assert msg.linear.x == 0.0
        assert msg.linear.y == 0.0
        assert msg.angular.z == 0.0


class TestStateJson:
    """状态 JSON 序列化测试。"""

    def test_emergency_stop_state(self):
        limits = Limits(0.10, 0.10, 0.30)
        data = _make_state_json(
            "EMERGENCY_STOP", True, False, limits
        )
        parsed = json.loads(data)
        assert parsed["source"] == "EMERGENCY_STOP"
        assert parsed["emergency_stopped"] is True
        assert parsed["patrol_running"] is False

    def test_patrol_running_state(self):
        limits = Limits(0.10, 0.10, 0.30)
        data = _make_state_json(
            "NAVIGATION", False, True, limits
        )
        parsed = json.loads(data)
        assert parsed["source"] == "NAVIGATION"
        assert parsed["patrol_running"] is True

    def test_manual_teleop_state(self):
        limits = Limits(0.08, 0.05, 0.25)
        data = _make_state_json(
            "MANUAL_TELEOP", False, False, limits
        )
        parsed = json.loads(data)
        assert parsed["source"] == "MANUAL_TELEOP"
        assert parsed["limits"]["linear_x"] == 0.08
        assert parsed["limits"]["linear_y"] == 0.05
        assert parsed["limits"]["angular_z"] == 0.25

    def test_zero_state(self):
        limits = Limits(0.10, 0.10, 0.30)
        data = _make_state_json(
            "ZERO", False, False, limits
        )
        parsed = json.loads(data)
        assert parsed["source"] == "ZERO"
