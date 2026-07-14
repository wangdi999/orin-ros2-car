"""
地砖裂缝检测模块（OpenCV边缘检测方案）。

使用Canny边缘检测 + 形态学特征筛选识别裂缝：
  1. 灰度化 → 高斯模糊
  2. Canny边缘检测
  3. 形态学闭运算连接断裂边缘
  4. 轮廓筛选（细长比 + 面积）
"""

import cv2
import numpy as np


# ---- 可调参数 ----
CANNY_LOW = 50          # Canny 低阈值
CANNY_HIGH = 150        # Canny 高阈值
BLUR_KERNEL = (5, 5)    # 高斯模糊核大小
MORPH_KERNEL = (3, 3)   # 闭运算核大小
MIN_CONTOUR_AREA = 80   # 最小轮廓面积（过滤噪点）
MIN_ASPECT_RATIO = 3.0  # 最小长宽比（裂缝细长特征）


class CrackDetector:
    """
    基于OpenCV的裂缝检测器。

    检测流程：
      gray → blur → Canny → morph close → findContours → 筛选细长轮廓
    """

    def __init__(
        self,
        canny_low=CANNY_LOW,
        canny_high=CANNY_HIGH,
        blur_kernel=BLUR_KERNEL,
        min_area=MIN_CONTOUR_AREA,
        min_aspect_ratio=MIN_ASPECT_RATIO,
    ):
        """
        初始化裂缝检测器。

        Args:
            canny_low: Canny低阈值
            canny_high: Canny高阈值
            blur_kernel: 高斯模糊核
            min_area: 最小轮廓面积
            min_aspect_ratio: 最小长宽比
        """
        self._canny_low = canny_low
        self._canny_high = canny_high
        self._blur_kernel = blur_kernel
        self._morph_kernel = MORPH_KERNEL
        self._min_area = min_area
        self._min_aspect_ratio = min_aspect_ratio

    def detect(self, image: np.ndarray) -> list:
        """
        检测图像中的裂缝区域。

        Args:
            image: BGR格式图像 (H, W, 3)

        Returns:
            检测框列表 [(x1, y1, x2, y2, confidence), ...]
            confidence 为归一化的裂缝概率估计值
        """
        if image is None or image.size == 0:
            return []

        # 1. 灰度化
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

        # 2. 高斯模糊去噪
        blurred = cv2.GaussianBlur(gray, self._blur_kernel, 0)

        # 3. Canny边缘检测
        edges = cv2.Canny(blurred, self._canny_low, self._canny_high)

        # 4. 闭运算连接断裂边缘
        kernel = cv2.getStructuringElement(
            cv2.MORPH_RECT, self._morph_kernel
        )
        closed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel)

        # 5. 查找轮廓
        contours, _ = cv2.findContours(
            closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )

        # 6. 筛选裂缝特征轮廓
        results = []
        for contour in contours:
            area = cv2.contourArea(contour)
            if area < self._min_area:
                continue

            # 最小外接矩形
            rect = cv2.minAreaRect(contour)
            (cx, cy), (rw, rh), angle = rect

            # 长宽比（长边/短边）
            long_side = max(rw, rh)
            short_side = min(rw, rh)
            if short_side < 1.0:
                continue
            aspect_ratio = long_side / short_side

            if aspect_ratio < self._min_aspect_ratio:
                continue

            # 计算归一化置信度（基于面积和长宽比）
            # 面积越大、越细长 → 置信度越高
            area_score = min(area / 500.0, 1.0)
            aspect_score = min((aspect_ratio - self._min_aspect_ratio) / 10.0, 1.0)
            confidence = 0.3 + 0.7 * (area_score * 0.3 + aspect_score * 0.7)

            # 获取轴对齐边界框
            x, y, w, h = cv2.boundingRect(contour)
            x1, y1 = x, y
            x2, y2 = x + w, y + h

            results.append((float(x1), float(y1), float(x2), float(y2), float(confidence)))

        return results

    def set_params(self, **kwargs):
        """动态调整检测参数。"""
        for key, value in kwargs.items():
            if hasattr(self, '_' + key):
                setattr(self, '_' + key, value)
