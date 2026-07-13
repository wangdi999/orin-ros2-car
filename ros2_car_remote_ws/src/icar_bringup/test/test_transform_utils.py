"""
transform_utils 单元测试。

测试 icar_bringup 的坐标变换工具函数：
  - quat_to_angle：四元数 → 偏航角
  - normalize_angle：角度归一化到 [-pi, pi]
"""

import sys
import os
import math
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# 检查 PyKDL 是否可用，不可用时跳过测试
try:
    import PyKDL
    PYKDL_AVAILABLE = True
except ImportError:
    PYKDL_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not PYKDL_AVAILABLE,
    reason="PyKDL 不可用（需要 ROS2 环境）"
)


class MockQuaternion:
    """模拟 geometry_msgs/Quaternion 消息。"""
    def __init__(self, x, y, z, w):
        self.x = x
        self.y = y
        self.z = z
        self.w = w


class TestQuatToAngle:
    """quat_to_angle 函数测试。"""

    def test_zero_rotation(self):
        """零旋转（四元数 (0, 0, 0, 1)）应返回 0。"""
        from icar_bringup.transform_utils import quat_to_angle
        q = MockQuaternion(0.0, 0.0, 0.0, 1.0)
        angle = quat_to_angle(q)
        assert abs(angle) < 1e-10, f"期望 0，得到 {angle}"

    def test_90_degree_yaw(self):
        """绕 Z 轴 90° 偏航。"""
        from icar_bringup.transform_utils import quat_to_angle
        # 90° yaw: qz = sin(45°), qw = cos(45°)
        import math
        half = math.radians(45.0)
        q = MockQuaternion(0.0, 0.0, math.sin(half), math.cos(half))
        angle = quat_to_angle(q)
        assert abs(angle - math.pi / 2) < 0.01, f"期望 ~1.57 rad，得到 {angle}"

    def test_negative_90_degree_yaw(self):
        """绕 Z 轴 -90° 偏航。"""
        from icar_bringup.transform_utils import quat_to_angle
        import math
        half = math.radians(-45.0)
        q = MockQuaternion(0.0, 0.0, math.sin(half), math.cos(half))
        angle = quat_to_angle(q)
        assert abs(angle + math.pi / 2) < 0.01, f"期望 ~-1.57 rad，得到 {angle}"

    def test_180_degree_yaw(self):
        """绕 Z 轴 180° 偏航，应返回 ±pi。"""
        from icar_bringup.transform_utils import quat_to_angle
        q = MockQuaternion(0.0, 0.0, 1.0, 0.0)
        angle = quat_to_angle(q)
        assert abs(abs(angle) - math.pi) < 0.01, f"期望 ±3.14 rad，得到 {angle}"


class TestNormalizeAngle:
    """normalize_angle 函数测试。"""

    def test_normal_angle_unchanged(self):
        """[-pi, pi] 范围内的角度不变。"""
        from icar_bringup.transform_utils import normalize_angle
        assert normalize_angle(0.0) == 0.0
        assert normalize_angle(1.0) == 1.0
        assert normalize_angle(-1.0) == -1.0
        assert abs(normalize_angle(math.pi) - math.pi) < 1e-10

    def test_angle_above_pi(self):
        """大于 pi 的角度应减去 2*pi。"""
        from icar_bringup.transform_utils import normalize_angle
        result = normalize_angle(2 * math.pi)
        assert abs(result) < 1e-10, f"期望 0，得到 {result}"

        result = normalize_angle(3 * math.pi)
        assert abs(result - math.pi) < 0.01, f"期望 ~pi，得到 {result}"

    def test_angle_below_negative_pi(self):
        """小于 -pi 的角度应加上 2*pi。"""
        from icar_bringup.transform_utils import normalize_angle
        result = normalize_angle(-2 * math.pi)
        assert abs(result) < 1e-10, f"期望 0，得到 {result}"

        result = normalize_angle(-3 * math.pi)
        assert abs(result + math.pi) < 0.01, f"期望 ~-pi，得到 {result}"

    def test_large_angle(self):
        """非常大的角度应正确归一化。"""
        from icar_bringup.transform_utils import normalize_angle
        result = normalize_angle(10 * math.pi)
        assert -math.pi <= result <= math.pi

    def test_extreme_negative_angle(self):
        """非常大的负角度应正确归一化。"""
        from icar_bringup.transform_utils import normalize_angle
        result = normalize_angle(-10 * math.pi)
        assert -math.pi <= result <= math.pi
