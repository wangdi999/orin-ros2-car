"""
可视化叠加模块。

在推理结果图像上绘制检测框、标签和置信度：
  - 正常人员：绿色框 + 标签 + 置信度
  - 异常行为：红色高亮闪烁框 + "ABNORMAL" 标签
  - 地砖裂缝：橙色框 + "crack" 标签
  - 通过 cv_bridge 转换为 ROS2 Image 消息
"""

import cv2
import numpy as np
from cv_bridge import CvBridge
from sensor_msgs.msg import Image


# 颜色定义（BGR）
COLOR_NORMAL = (0, 255, 0)          # 绿色 - 正常人员检测
COLOR_ABNORMAL = (0, 0, 255)        # 红色 - 异常行为
COLOR_ABNORMAL_DIM = (0, 0, 100)    # 暗红色（闪烁暗相）
COLOR_CRACK = (0, 165, 255)         # 橙色 - 地砖裂缝

# 闪烁控制
FLASH_INTERVAL_FRAMES = 5  # 每隔 N 帧切换亮/暗


class DetectionVisualizer:
    """
    检测结果可视化器。

    在原始图像上叠加检测框和标签，
    通过 cv_bridge 转换为 ROS Image 消息发布。
    """

    def __init__(self):
        """初始化可视化器和 cv_bridge 实例。"""
        self._bridge = CvBridge()
        self._flash_counter = 0

    def draw_detections(
        self,
        image: np.ndarray,
        bboxes: list,
        confidences: list,
        danger_types: list,
    ) -> np.ndarray:
        """
        在图像上绘制所有检测结果。

        Args:
            image: BGR 格式的原始图像 (H, W, 3)
            bboxes: 检测框列表 [(x1,y1,x2,y2), ...]
            confidences: 置信度列表 [float, ...]
            danger_types: 危险类型列表 ["person_detected"|"abnormal_behavior"|"cracked_tile", ...]

        Returns:
            叠加了检测框的 BGR 图像
        """
        self._flash_counter += 1
        bright_phase = (self._flash_counter // FLASH_INTERVAL_FRAMES) % 2 == 0

        result = image.copy()

        for i, bbox in enumerate(bboxes):
            x1, y1, x2, y2 = map(int, bbox)
            confidence = confidences[i] if i < len(confidences) else 0.0
            danger_type = (
                danger_types[i] if i < len(danger_types) else "person_detected"
            )

            if danger_type == "cracked_tile":
                # 地砖裂缝：橙色框
                color = COLOR_CRACK
                thickness = 2
                label = "crack {:.2f}".format(confidence)
            elif danger_type == "abnormal_behavior":
                # 异常行为：红色闪烁框
                color = COLOR_ABNORMAL if bright_phase else COLOR_ABNORMAL_DIM
                thickness = 3
                label = "ABNORMAL {:.2f}".format(confidence)
            else:
                # 正常人员：绿色框
                color = COLOR_NORMAL
                thickness = 2
                label = "person {:.2f}".format(confidence)

            # 绘制矩形框
            cv2.rectangle(result, (x1, y1), (x2, y2), color, thickness)

            # 绘制标签背景
            (label_w, label_h), baseline = cv2.getTextSize(
                label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1
            )
            cv2.rectangle(
                result,
                (x1, y1 - label_h - 5),
                (x1 + label_w, y1),
                color,
                -1,
            )

            # 绘制标签文字
            cv2.putText(
                result,
                label,
                (x1, y1 - 5),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (255, 255, 255),  # 白色文字
                1,
                cv2.LINE_AA,
            )

        return result

    def to_ros_image(self, image: np.ndarray, encoding: str = "bgr8") -> Image:
        """
        将 OpenCV 图像转换为 ROS2 Image 消息。

        Args:
            image: BGR 或指定编码的 numpy 图像
            encoding: 图像编码格式，默认 "bgr8"

        Returns:
            sensor_msgs.msg.Image 消息
        """
        return self._bridge.cv2_to_imgmsg(image, encoding=encoding)
