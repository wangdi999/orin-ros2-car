"""
DetectionVisualizer 单元测试。

测试可视化叠加模块的核心功能：
  - 正常人员检测框（绿色）
  - 异常行为检测框（红色闪烁）
  - 空检测列表
  - 闪烁相位切换
"""

import sys
import os
import numpy as np
import pytest

# 路径注入
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Mock cv_bridge 和 sensor_msgs（离线测试无需 ROS2）
import importlib

# 如果 cv_bridge 不可用，提供 mock
try:
    import cv_bridge
except ImportError:
    # 创建一个 mock 模块
    class MockCvBridge:
        def cv2_to_imgmsg(self, image, encoding="bgr8"):
            return MockImage(encoding, image)

    class MockImage:
        def __init__(self, encoding, data):
            self.encoding = encoding
            self.data = data
            self.header = MockHeader()

    class MockHeader:
        def __init__(self):
            self.stamp = None
            self.frame_id = ""

    sys.modules["cv_bridge"] = type(sys)("cv_bridge")
    sys.modules["cv_bridge"].CvBridge = MockCvBridge
    sys.modules["sensor_msgs"] = type(sys)("sensor_msgs")
    sys.modules["sensor_msgs.msg"] = type(sys)("sensor_msgs.msg")
    sys.modules["sensor_msgs.msg"].Image = MockImage

from car_ai_vision.visualizer import DetectionVisualizer


class TestDetectionVisualizer:
    """DetectionVisualizer 单元测试。"""

    @pytest.fixture
    def visualizer(self):
        """创建可视化器实例。"""
        return DetectionVisualizer()

    @pytest.fixture
    def blank_image(self):
        """创建空白测试图像 (480x640 BGR)。"""
        return np.zeros((480, 640, 3), dtype=np.uint8)

    def test_draw_normal_detection(self, visualizer, blank_image):
        """正常人员检测应绘制绿色框 + person 标签。"""
        bboxes = [(100, 150, 250, 400)]
        confidences = [0.85]
        danger_types = ["person_detected"]

        result = visualizer.draw_detections(
            blank_image, bboxes, confidences, danger_types
        )

        # 验证输出形状不变
        assert result.shape == blank_image.shape
        # 验证输出不是原始图像（已被修改）
        assert not np.array_equal(result, blank_image)

    def test_draw_abnormal_detection(self, visualizer, blank_image):
        """异常行为检测应绘制红色框 + ABNORMAL 标签。"""
        bboxes = [(100, 50, 300, 140)]
        confidences = [0.92]
        danger_types = ["abnormal_behavior"]

        result = visualizer.draw_detections(
            blank_image, bboxes, confidences, danger_types
        )

        assert result.shape == blank_image.shape
        assert not np.array_equal(result, blank_image)

    def test_draw_multiple_detections(self, visualizer, blank_image):
        """多目标检测：正常 + 异常混合。"""
        bboxes = [
            (50, 100, 150, 350),    # 站立人员
            (200, 80, 400, 160),    # 倒地人员（异常）
            (450, 120, 550, 380),   # 站立人员
        ]
        confidences = [0.75, 0.88, 0.62]
        danger_types = ["person_detected", "abnormal_behavior", "person_detected"]

        result = visualizer.draw_detections(
            blank_image, bboxes, confidences, danger_types
        )

        assert result.shape == blank_image.shape
        assert not np.array_equal(result, blank_image)

    def test_empty_detections(self, visualizer, blank_image):
        """空检测列表应返回原图副本。"""
        result = visualizer.draw_detections(
            blank_image, [], [], []
        )

        assert result.shape == blank_image.shape
        # 空检测时绘制不应改变图像内容（仅 copy）
        assert np.array_equal(result, blank_image)

    def test_mismatched_list_lengths(self, visualizer, blank_image):
        """confidences 和 danger_types 长度不足时不应崩溃。"""
        bboxes = [(100, 100, 200, 300), (300, 100, 400, 300)]
        confidences = [0.80]  # 只有1个，第2个应默认为 0.0
        danger_types = ["abnormal_behavior"]  # 第2个应默认为 person_detected

        result = visualizer.draw_detections(
            blank_image, bboxes, confidences, danger_types
        )

        assert result.shape == blank_image.shape

    def test_flash_toggle(self, visualizer, blank_image):
        """闪烁相位应在亮/暗之间切换。"""
        from car_ai_vision.visualizer import FLASH_INTERVAL_FRAMES
        bboxes = [(100, 50, 300, 140)]
        confidences = [0.90]
        danger_types = ["abnormal_behavior"]

        visualizer._flash_counter = 0  # 亮相
        result1 = visualizer.draw_detections(
            blank_image.copy(), bboxes, confidences, danger_types
        )

        visualizer._flash_counter = FLASH_INTERVAL_FRAMES  # 暗相
        result2 = visualizer.draw_detections(
            blank_image.copy(), bboxes, confidences, danger_types
        )

        # 亮相和暗相结果应不同
        assert not np.array_equal(result1, result2)

    def test_bbox_coordinate_handling(self, visualizer, blank_image):
        """测试负坐标和超界坐标不会崩溃。"""
        bboxes = [(-10, -10, 100, 100)]
        confidences = [0.70]
        danger_types = ["person_detected"]

        result = visualizer.draw_detections(
            blank_image, bboxes, confidences, danger_types
        )
        assert result.shape == blank_image.shape

    def test_to_ros_image_bgr8(self, visualizer, blank_image):
        """to_ros_image 应能被调用且不抛异常。"""
        ros_img = visualizer.to_ros_image(blank_image, encoding="bgr8")
        assert ros_img is not None
