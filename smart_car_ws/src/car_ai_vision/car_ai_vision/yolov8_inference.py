"""
YOLOv8-TensorRT 边缘推理节点。

在 Jetson Orin Nano 主机上运行，通过 ROS_DOMAIN_ID=32 与
Docker 容器内其他 ROS2 节点通信。

线程模型：
  - Main Thread: ROS2 spin + 回调
  - Inference Thread: 取帧 → 推理 → 发布报警
  - Depth Thread: 深度数据关联

功能：
  - 订阅 /camera/color/image_raw (RGB) + /camera/depth/image_raw (深度)
  - 订阅 /odom (里程计) + /tf /tf_static (坐标变换)
  - YOLOv8-small TensorRT FP16 推理，COCO person 类检测
  - 异常行为规则引擎判定（倒地+静止+深度一致性）
  - 报警消抖：按 danger_type 独立冷却
  - 检测框可视化叠加发布到 /camera/ai_detections
  - 异常行为自动截帧保存前后30帧
  - 发布 Alarm 消息到 /chassis/ai_alarm
"""

import math
import os
import sys
import threading
import time
import traceback
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Tuple, List, Optional

import cv2
import numpy as np
# 兼容 TensorRT 8.5 + numpy >= 1.24 (np.bool 已移除)
np.bool = bool
np.int = int
np.float = float
np.complex = complex
np.object = object
np.str = str

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile
from rclpy.parameter import Parameter

from sensor_msgs.msg import Image
from nav_msgs.msg import Odometry
from tf2_msgs.msg import TFMessage
from geometry_msgs.msg import TransformStamped

# ROS2 消息接口（依赖 car_ai_interfaces 包编译）
try:
    from car_ai_interfaces.msg import Alarm
except ImportError:
    Alarm = None

from cv_bridge import CvBridge, CvBridgeError

# 内部模块
from car_ai_vision.alarm_manager import AlarmDebouncer
from car_ai_vision.abnormal_behavior import AbnormalBehaviorDetector
from car_ai_vision.visualizer import DetectionVisualizer
from car_ai_vision.capture_manager import CaptureManager


# ============================================================
# 常量定义
# ============================================================

# 模型路径
DEFAULT_MODEL_PATH = os.path.join(
    str(Path.home()), "smart_car_ws", "models", "yolov8s.engine"
)
DEFAULT_ONNX_PATH = os.path.join(
    str(Path.home()), "smart_car_ws", "models", "yolov8s.onnx"
)
CRACK_ENGINE_PATH = os.path.join(
    str(Path.home()), "smart_car_ws", "models", "crack_yolo.engine"
)
CRACK_ONNX_PATH = os.path.join(
    str(Path.home()), "smart_car_ws", "models", "crack_yolo.onnx"
)

# 推理参数
CONFIDENCE_THRESHOLD = 0.5
COCO_PERSON_CLASS_ID = 0  # YOLOv8 COCO 预训练中 person 的 class_id

# 超时与限制
ODOM_TIMEOUT_SEC = 5.0
MAX_IMAGE_WIDTH = 4096
MAX_IMAGE_HEIGHT = 4096
MIN_IMAGE_WIDTH = 32
MIN_IMAGE_HEIGHT = 32

# 有效 danger_type 枚举值
VALID_DANGER_TYPES = {
    "person_detected",
    "abnormal_behavior",
    "cracked_tile",
}


# ============================================================
# 数据校验工具
# ============================================================

def validate_confidence(confidence: float) -> bool:
    """校验置信度在 [0.0, 1.0] 且非 NaN/Inf。"""
    if confidence is None:
        return False
    return (
        not math.isnan(confidence)
        and not math.isinf(confidence)
        and 0.0 <= confidence <= 1.0
    )


def validate_danger_type(danger_type: str) -> bool:
    """校验 danger_type 为有效枚举值。"""
    return danger_type in VALID_DANGER_TYPES


def validate_coordinate(pos_x: float, pos_y: float) -> bool:
    """校验坐标为有限值（不拒绝原点，odom新鲜度已单独检查）。"""
    if pos_x is None or pos_y is None:
        return False
    if math.isnan(pos_x) or math.isnan(pos_y):
        return False
    if math.isinf(pos_x) or math.isinf(pos_y):
        return False
    return True


def make_iso8601_utc() -> str:
    """生成 ISO 8601 UTC 时间戳字符串。"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ============================================================
# 模型加载
# ============================================================

def load_model(logger, model_path: str, onnx_path: str):
    """
    加载 YOLO 模型，优先级：.engine > .onnx > 异常退出。

    Args:
        logger: ROS2 logger 实例
        model_path: TensorRT engine 文件路径
        onnx_path: ONNX 模型文件路径（降级方案）

    Returns:
        Ultralytics YOLO model 实例

    Raises:
        SystemExit: 所有模型路径均不可用时优雅退出
    """
    from ultralytics import YOLO

    if os.path.exists(model_path):
        logger.info(f"加载 TensorRT engine: {model_path}")
        try:
            model = YOLO(model_path)
            logger.info("TensorRT engine 加载成功")
            return model
        except Exception as e:
            logger.error(f"TensorRT engine 加载失败: {e}")
    else:
        logger.warn(f"TensorRT engine 不存在: {model_path}")

    # 降级：尝试 ONNX
    if os.path.exists(onnx_path):
        logger.warn(f"回退加载 ONNX 模型: {onnx_path}")
        try:
            model = YOLO(onnx_path)
            logger.warn("ONNX 模型加载成功（非最优性能）")
            return model
        except Exception as e:
            logger.error(f"ONNX 模型加载失败: {e}")
    else:
        logger.error(f"ONNX 模型不存在: {onnx_path}")

    logger.error("所有模型加载路径均失败，无法继续运行")
    raise SystemExit(1)


# ============================================================
# 主推理节点
# ============================================================

class YOLOv8InferenceNode(Node):
    """
    YOLOv8-TensorRT 推理节点。

    三线程架构：
      - Main Thread:  ROS2 spin + 回调
      - Inference Thread: 取帧→推理→报警判定→发布
      - Depth Thread: 深度帧缓存管理（轻度）

    设计要点：
      - 自动跳帧：推理耗时期间到达的新帧仅保留最新一帧
      - 永不阻塞 ROS2：所有回调仅做轻量拷贝
    """

    def __init__(self):
        super().__init__("yolov8_inference")

        # ---- 日志级别 ----
        self._debug = self.declare_parameter("debug", False).value
        if self._debug:
            self.get_logger().set_level(rclpy.logging.LoggingSeverity.INFO)
        else:
            self.get_logger().set_level(rclpy.logging.LoggingSeverity.WARN)

        self.get_logger().info("=== YOLOv8 Inference Node 启动 ===")

        # ---- 模型加载 ----
        model_path = os.environ.get(
            "YOLO_MODEL_PATH", DEFAULT_MODEL_PATH
        )
        onnx_path = os.environ.get(
            "YOLO_ONNX_PATH", DEFAULT_ONNX_PATH
        )
        self._model = load_model(self.get_logger(), model_path, onnx_path)

        # ---- CV Bridge ----
        self._bridge = CvBridge()

        # ---- QoS 配置 ----
        sensor_qos = QoSProfile(
            depth=1,
            reliability=rclpy.qos.ReliabilityPolicy.BEST_EFFORT,
        )
        alarm_qos = QoSProfile(depth=10)

        # ---- 订阅 ----
        self._color_sub = self.create_subscription(
            Image,
            "/camera/color/image_raw",
            self._color_callback,
            sensor_qos,
        )
        self._depth_sub = self.create_subscription(
            Image,
            "/camera/depth/image_raw",
            self._depth_callback,
            sensor_qos,
        )
        self._odom_sub = self.create_subscription(
            Odometry,
            "/odom",
            self._odom_callback,
            sensor_qos,
        )

        # TF 订阅（tf2_ros 的简版：直接订阅 TFMessage）
        self._tf_sub = self.create_subscription(
            TFMessage,
            "/tf",
            self._tf_callback,
            QoSProfile(depth=100),
        )
        self._tf_static_sub = self.create_subscription(
            TFMessage,
            "/tf_static",
            self._tf_static_callback,
            QoSProfile(
                depth=100,
                durability=rclpy.qos.DurabilityPolicy.TRANSIENT_LOCAL,
            ),
        )

        # ---- 发布器 ----
        if Alarm is not None:
            self._alarm_pub = self.create_publisher(
                Alarm, "/chassis/ai_alarm", alarm_qos
            )
        else:
            self._alarm_pub = None
            self.get_logger().error(
                "car_ai_interfaces.Alarm 消息类型不可用，报警发布功能已禁用"
            )
        self._detections_pub = self.create_publisher(
            Image, "/camera/ai_detections", alarm_qos
        )

        # ---- 线程同步 ----
        self._color_lock = threading.Lock()
        self._depth_lock = threading.Lock()
        self._odom_lock = threading.Lock()
        self._tf_lock = threading.Lock()

        # ---- 最新数据缓存 ----
        self._latest_color: Optional[np.ndarray] = None
        self._latest_color_header: Optional[dict] = None
        self._color_new = threading.Event()

        self._latest_depth: Optional[np.ndarray] = None
        self._latest_depth_header: Optional[dict] = None

        self._latest_odom: Optional[Odometry] = None
        self._last_odom_time: float = 0.0

        # TF 缓存（简单 odom→map 变换用）
        self._tf_odom_to_map: Optional[TransformStamped] = None

        # ---- 功能模块 ----
        self._debouncer = AlarmDebouncer()
        self._abnormal_detector = AbnormalBehaviorDetector(
            consecutive_frames=15, iou_threshold=0.5
        )
        self._visualizer = DetectionVisualizer()
        self._capture_manager = CaptureManager(buffer_size=30)

        # ---- 裂缝检测模型 ----
        crack_engine = os.environ.get(
            "CRACK_ENGINE_PATH", CRACK_ENGINE_PATH
        )
        crack_onnx = os.environ.get(
            "CRACK_ONNX_PATH", CRACK_ONNX_PATH
        )
        self._crack_model = load_model(
            self.get_logger(), crack_engine, crack_onnx
        )
        # 兼容 ultralytics 8.2.x AutoBackend 缺少 task 属性
        if (hasattr(self._crack_model, 'model')
                and not isinstance(self._crack_model.model, str)
                and not hasattr(self._crack_model.model, 'task')):
            self._crack_model.model.task = 'segment'

        # ---- 运行控制 ----
        self._running = True
        self._inference_ready = threading.Event()

        # ---- 性能统计 ----
        self._stats_lock = threading.Lock()
        self._frame_count = 0
        self._total_inference_ms = 0.0
        self._total_alarm_latency_ms = 0.0
        self._alarm_count = 0
        self._last_stats_time = time.time()
        self._stats_interval = 5.0  # 每5秒输出一次性能统计
        self._fps = 0.0

        # 滚动窗口（用于可视化帧上的实时FPS叠加）
        self._fps_window = deque(maxlen=30)      # 最近30帧时间戳
        self._latency_window = deque(maxlen=30)   # 最近30帧推理延迟(ms)

        # ---- 启动推理线程 ----
        self._inference_thread = threading.Thread(
            target=self._inference_loop, name="InferenceThread", daemon=True
        )
        self._inference_thread.start()

        self.get_logger().info("推理线程已启动，等待图像数据...")

    # ========================================================
    # 回调方法（主线程，仅做轻量拷贝）
    # ========================================================

    def _color_callback(self, msg: Image) -> None:
        """RGB 图像回调：CvBridge 转换 + 缓存。"""
        if not self._running:
            return

        try:
            # 编码校验
            if not msg.encoding or len(msg.encoding) < 3:
                self.get_logger().warn(
                    f"不支持的图像编码: '{msg.encoding}'，丢弃帧"
                )
                return

            # 尺寸校验
            if (
                msg.width < MIN_IMAGE_WIDTH
                or msg.width > MAX_IMAGE_WIDTH
                or msg.height < MIN_IMAGE_HEIGHT
                or msg.height > MAX_IMAGE_HEIGHT
            ):
                self.get_logger().warn(
                    f"图像尺寸异常 ({msg.width}x{msg.height})，丢弃帧"
                )
                return

            # 空数据校验
            if msg.data is None or len(msg.data) == 0:
                self.get_logger().warn("收到空图像数据，丢弃帧")
                return

            cv_image = self._bridge.imgmsg_to_cv2(
                msg, desired_encoding="bgr8"
            )

            with self._color_lock:
                self._latest_color = cv_image
                self._latest_color_header = {
                    "stamp": msg.header.stamp,
                    "frame_id": msg.header.frame_id,
                }
                self._color_new.set()

        except CvBridgeError as e:
            self.get_logger().warn(f"CvBridgeError 转换失败: {e}，丢弃帧")
        except Exception as e:
            self.get_logger().error(f"图像回调异常: {e}")

    def _depth_callback(self, msg: Image) -> None:
        """深度图像回调。"""
        if not self._running:
            return
        try:
            depth_image = self._bridge.imgmsg_to_cv2(
                msg, desired_encoding="passthrough"
            )
            with self._depth_lock:
                self._latest_depth = depth_image
                self._latest_depth_header = {
                    "stamp": msg.header.stamp,
                    "frame_id": msg.header.frame_id,
                }
        except CvBridgeError as e:
            self.get_logger().warn(f"深度图 CvBridgeError: {e}，丢弃帧")
        except Exception as e:
            self.get_logger().error(f"深度图回调异常: {e}")

    def _odom_callback(self, msg: Odometry) -> None:
        """里程计回调。"""
        if not self._running:
            return
        with self._odom_lock:
            self._latest_odom = msg
            self._last_odom_time = time.time()

    def _tf_callback(self, msg: TFMessage) -> None:
        """TF 动态变换回调（提取 odom→map 变换）。"""
        if not self._running:
            return
        with self._tf_lock:
            for transform in msg.transforms:
                if (
                    transform.header.frame_id == "map"
                    and transform.child_frame_id == "odom"
                ):
                    self._tf_odom_to_map = transform
                elif (
                    transform.header.frame_id == "odom"
                    and transform.child_frame_id == "map"
                ):
                    # 逆变换，记录但不处理
                    pass

    def _tf_static_callback(self, msg: TFMessage) -> None:
        """TF 静态变换回调。"""
        self._tf_callback(msg)

    # ========================================================
    # 坐标变换
    # ========================================================

    def _transform_position(
        self, odom_x: float, odom_y: float, odom_z: float = 0.0
    ) -> Tuple[float, float, str]:
        """
        将 odom 坐标变换为 map 坐标。

        优先使用 TF odom→map 变换，失败时回退 odom 坐标。

        Args:
            odom_x, odom_y, odom_z: odom 坐标系下的位置

        Returns:
            (pos_x, pos_y, coord_frame) 元组
        """
        with self._tf_lock:
            tf = self._tf_odom_to_map

        if tf is not None:
            try:
                tx = tf.transform.translation.x
                ty = tf.transform.translation.y
                tz = tf.transform.translation.z
                map_x = odom_x + tx
                map_y = odom_y + ty
                return (map_x, map_y, "map")
            except Exception as e:
                self.get_logger().warn(
                    f"TF 坐标变换失败: {e}，回退 odom 坐标"
                )

        return (odom_x, odom_y, "odom")

    def _get_current_position(self) -> Optional[Tuple[float, float, str]]:
        """
        获取当前机器人位置。

        Returns:
            (pos_x, pos_y, coord_frame) 或 None（odom 超时）
        """
        with self._odom_lock:
            odom = self._latest_odom
            last_time = self._last_odom_time

        if odom is None:
            return None

        # odom 超时检查
        if time.time() - last_time > ODOM_TIMEOUT_SEC:
            self.get_logger().warn(
                f"/odom 超时 ({time.time() - last_time:.1f}s > "
                f"{ODOM_TIMEOUT_SEC}s)，停止发布报警"
            )
            return None

        odom_x = odom.pose.pose.position.x
        odom_y = odom.pose.pose.position.y

        return self._transform_position(odom_x, odom_y)

    # ========================================================
    # 深度数据提取
    # ========================================================

    def _extract_depth_values(
        self, bboxes: list
    ) -> List[Optional[float]]:
        """
        从深度图中提取各检测框区域的深度值。

        Args:
            bboxes: 检测框列表 [(x1,y1,x2,y2), ...]

        Returns:
            每个框对应的深度中位数列表，None 表示无深度数据
        """
        with self._depth_lock:
            depth = self._latest_depth

        if depth is None:
            return [None] * len(bboxes)

        h, w = depth.shape[:2]
        results = []

        for bbox in bboxes:
            x1, y1, x2, y2 = map(int, bbox)
            x1 = max(0, min(x1, w - 1))
            y1 = max(0, min(y1, h - 1))
            x2 = max(x1 + 1, min(x2, w))
            y2 = max(y1 + 1, min(y2, h))

            roi = depth[y1:y2, x1:x2]
            if roi.size == 0:
                results.append(None)
                continue

            # 过滤无效深度值（0 或 NaN）
            valid = roi[(roi > 0) & (~np.isnan(roi))]
            if valid.size == 0:
                results.append(None)
            else:
                results.append(float(np.median(valid)))

        return results

    # ========================================================
    # 数据校验（发布前）
    # ========================================================

    def _validate_alarm_data(
        self,
        danger_type: str,
        confidence: float,
        pos_x: float,
        pos_y: float,
        coord_frame: str,
    ) -> bool:
        """
        对报警数据进行完整性校验，全部通过才允许发布。

        Returns:
            True 表示校验通过
        """
        if not validate_danger_type(danger_type):
            self.get_logger().error(
                f"数据校验失败: 无效 danger_type='{danger_type}'"
            )
            return False

        if not validate_confidence(confidence):
            self.get_logger().error(
                f"数据校验失败: 无效 confidence={confidence}"
            )
            return False

        if not validate_coordinate(pos_x, pos_y):
            self.get_logger().warn(
                f"数据校验失败: 无效坐标 ({pos_x}, {pos_y})"
            )
            return False

        if coord_frame not in ("map", "odom"):
            self.get_logger().error(
                f"数据校验失败: 无效 coord_frame='{coord_frame}'"
            )
            return False

        return True

    # ========================================================
    # 推理主循环（独立线程）
    # ========================================================

    def _inference_loop(self) -> None:
        """推理线程主循环：取帧 → 推理 → 判定 → 发布。"""
        self.get_logger().info("推理循环开始")

        while self._running and rclpy.ok():
            # 等待新帧（自动跳帧：仅处理最新帧）
            if not self._color_new.wait(timeout=0.5):
                continue
            self._color_new.clear()

            # ---- 获取最新数据 ----
            with self._color_lock:
                color_image = self._latest_color
                color_header = self._latest_color_header

            if color_image is None:
                continue

            try:
                # ---- YOLO 推理 ----
                t0 = time.time()
                results = self._model(
                    color_image,
                    conf=CONFIDENCE_THRESHOLD,
                    classes=[COCO_PERSON_CLASS_ID],  # 仅检测 person
                    verbose=False,
                )
                inference_ms = (time.time() - t0) * 1000

                # 更新滚动窗口（用于可视化叠加）
                now_ts = time.time()
                with self._stats_lock:
                    self._frame_count += 1
                    self._total_inference_ms += inference_ms
                    self._fps_window.append(now_ts)
                    self._latency_window.append(inference_ms)

                # ---- 提取检测结果 ----
                bboxes = []
                confidences = []

                if results and len(results) > 0:
                    boxes = results[0].boxes
                    if boxes is not None and len(boxes) > 0:
                        for box in boxes:
                            xyxy = box.xyxy[0].cpu().numpy()
                            conf = float(box.conf[0].cpu().numpy())
                            bboxes.append(tuple(xyxy.tolist()))
                            confidences.append(conf)

                # ---- 裂缝检测（YOLO模型，每帧都跑） ----
                crack_results = []
                try:
                    cr = self._crack_model(
                        color_image, conf=0.35, verbose=False
                    )
                    if cr and len(cr) > 0:
                        boxes = cr[0].boxes
                        if boxes is not None and len(boxes) > 0:
                            for box in boxes:
                                xyxy = box.xyxy[0].cpu().numpy()
                                conf = float(box.conf[0].cpu().numpy())
                                crack_results.append(
                                    (float(xyxy[0]), float(xyxy[1]),
                                     float(xyxy[2]), float(xyxy[3]), conf)
                                )
                except Exception as e:
                    self.get_logger().warn(
                        "裂缝检测异常: {}".format(e)
                    )

                # ---- 合并裂缝结果 ----
                num_person = len(bboxes)
                for cr in crack_results:
                    bboxes.append((cr[0], cr[1], cr[2], cr[3]))
                    confidences.append(cr[4])
                num_crack = len(crack_results)

                # ---- 无任何检测：继续循环 ----
                if not bboxes:
                    vis_image = self._visualizer.draw_detections(
                        color_image, [], [], []
                    )
                    self._overlay_perf_info(
                        vis_image, 0, inference_ms
                    )
                    self._publish_visualization(vis_image, color_header)
                    continue

                # ---- 深度关联（仅对person检测框） ----
                person_bboxes = bboxes[:num_person]
                depth_vals = self._extract_depth_values(person_bboxes)

                # ---- 异常行为判定（仅对person） ----
                is_abnormal_list = self._abnormal_detector.update(
                    person_bboxes, depth_vals
                )

                # ---- 构建 danger_types ----
                danger_types = []
                for i in range(num_person):
                    if is_abnormal_list[i]:
                        danger_types.append("abnormal_behavior")
                    else:
                        danger_types.append("person_detected")
                for _ in range(num_crack):
                    danger_types.append("cracked_tile")

                # ---- 获取当前位置 ----
                position = self._get_current_position()

                # ---- 逐目标处理 ----
                for i, bbox in enumerate(bboxes):
                    confidence = confidences[i]
                    danger_type = danger_types[i]

                    # 消抖检查
                    if not self._debouncer.should_publish(danger_type):
                        remaining = self._debouncer.get_cooldown_remaining(
                            danger_type
                        )
                        self.get_logger().warn(
                            f"[告警抑制] {danger_type} "
                            f"剩余冷却 {remaining:.1f}s"
                        )
                        continue

                    # 构建坐标（odom不可用时降级为零点）
                    if position is not None:
                        pos_x, pos_y, coord_frame = position
                    else:
                        pos_x, pos_y, coord_frame = 0.0, 0.0, "odom"
                        self.get_logger().warn(
                            "[告警降级] /odom 不可用，坐标置为(0,0)。"
                            "联调时需确保底盘模块运行。"
                        )

                    # 数据校验
                    if not self._validate_alarm_data(
                        danger_type, confidence, pos_x, pos_y, coord_frame
                    ):
                        continue

                    # ---- 发布报警 ----
                    alarm_t0 = time.time()
                    self._publish_alarm(
                        danger_type=danger_type,
                        confidence=confidence,
                        pos_x=pos_x,
                        pos_y=pos_y,
                        coord_frame=coord_frame,
                        bbox=bbox,
                    )
                    alarm_latency_ms = (time.time() - alarm_t0) * 1000
                    with self._stats_lock:
                        self._alarm_count += 1
                        self._total_alarm_latency_ms += alarm_latency_ms

                    # ---- 异常行为截帧 ----
                    if danger_type == "abnormal_behavior":
                        self._capture_manager.trigger()
                        self.get_logger().warn(
                            f"触发异常行为截帧！"
                            f"confidence={confidence:.2f} "
                            f"pos=({pos_x:.2f},{pos_y:.2f})"
                        )

                # ---- 发布可视化帧 ----
                vis_image = self._visualizer.draw_detections(
                    color_image, bboxes, confidences, danger_types
                )
                # 叠加性能信息到可视化帧
                self._overlay_perf_info(
                    vis_image, len(bboxes), inference_ms
                )
                self._publish_visualization(vis_image, color_header)

                # ---- 截帧缓冲区更新 ----
                self._capture_manager.feed(color_image)

                # ---- 定期输出性能统计 ----
                self._log_performance_stats()

            except MemoryError:
                self.get_logger().error(
                    "GPU OOM！清理缓存并重试..."
                )
                self._clear_gpu_cache()
                # 重试一次
                try:
                    results = self._model(
                        color_image,
                        conf=CONFIDENCE_THRESHOLD,
                        classes=[COCO_PERSON_CLASS_ID],
                        verbose=False,
                    )
                except MemoryError:
                    self.get_logger().error(
                        "GPU OOM 重试失败，跳过当前帧"
                    )
                    continue
            except Exception as e:
                self.get_logger().error(
                    f"推理异常: {e}\n{traceback.format_exc()}"
                )
                continue

        self.get_logger().info("推理循环结束")

    # ========================================================
    # 性能信息叠加
    # ========================================================

    def _overlay_perf_info(
        self,
        image: np.ndarray,
        num_detections: int,
        inference_ms: float,
    ) -> None:
        """
        在图像左上角叠加性能信息（直接修改传入图像）。

        叠加内容：
          - 实时FPS（基于30帧滚动窗口）
          - 平均推理延迟（ms）
          - 当前检测目标数
        """
        with self._stats_lock:
            fps = 0.0
            if len(self._fps_window) >= 2:
                dt = (
                    self._fps_window[-1] - self._fps_window[0]
                )
                fps = (len(self._fps_window) - 1) / dt if dt > 0 else 0.0
            avg_latency = (
                sum(self._latency_window) / len(self._latency_window)
                if self._latency_window else inference_ms
            )

        # 构建叠加文字
        lines = [
            "FPS: {:.1f}".format(fps),
            "Latency: {:.0f}ms".format(avg_latency),
            "Detections: {}".format(num_detections),
        ]

        # 绘制半透明背景
        overlay = image.copy()
        panel_h = 20 * len(lines) + 12
        panel_w = 180
        cv2.rectangle(
            overlay, (8, 8), (8 + panel_w, 8 + panel_h),
            (0, 0, 0), -1,
        )
        cv2.addWeighted(overlay, 0.5, image, 0.5, 0, image)

        # 绘制文字
        for i, line in enumerate(lines):
            y = 28 + i * 20
            cv2.putText(
                image, line, (16, y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                (0, 255, 0), 1, cv2.LINE_AA,
            )

    # ========================================================
    # 发布方法
    # ========================================================

    def _publish_alarm(
        self,
        danger_type: str,
        confidence: float,
        pos_x: float,
        pos_y: float,
        coord_frame: str,
        bbox: tuple,
    ) -> None:
        """
        发布单条 Alarm 消息到 /chassis/ai_alarm。

        每帧每个目标独立发布一条 Alarm（不聚合）。
        """
        if Alarm is None or self._alarm_pub is None:
            self.get_logger().error(
                "car_ai_interfaces.Alarm 未导入或发布器未初始化，跳过报警发布"
            )
            return

        try:
            msg = Alarm()
            msg.danger_type = danger_type
            msg.confidence = float(confidence)
            msg.timestamp = make_iso8601_utc()
            msg.pos_x = float(pos_x)
            msg.pos_y = float(pos_y)
            msg.coord_frame = coord_frame
            msg.bbox_center_x = float(
                (bbox[0] + bbox[2]) / 2.0
            )
            msg.bbox_center_y = float(
                (bbox[1] + bbox[3]) / 2.0
            )
            msg.bbox_width = float(bbox[2] - bbox[0])
            msg.bbox_height = float(bbox[3] - bbox[1])

            self._alarm_pub.publish(msg)

            if self._debug:
                self.get_logger().info(
                    f"发布报警: {danger_type} "
                    f"conf={confidence:.2f} "
                    f"pos=({pos_x:.2f},{pos_y:.2f})@{coord_frame}"
                )

        except Exception as e:
            self.get_logger().error(
                f"发布报警异常: {e}，下一周期重试"
            )

    def _publish_visualization(
        self,
        image: np.ndarray,
        header: Optional[dict] = None,
    ) -> None:
        """发布可视化图像到 /camera/ai_detections。"""
        try:
            ros_image = self._visualizer.to_ros_image(image)
            if header is not None:
                ros_image.header.stamp = header.get(
                    "stamp", self.get_clock().now().to_msg()
                )
                ros_image.header.frame_id = header.get(
                    "frame_id", "camera_color_frame"
                )
            else:
                ros_image.header.stamp = (
                    self.get_clock().now().to_msg()
                )
                ros_image.header.frame_id = "camera_color_frame"
            self._detections_pub.publish(ros_image)
        except Exception as e:
            self.get_logger().error(
                f"发布可视化异常: {e}，下一周期重试"
            )

    # ========================================================
    # 性能监控
    # ========================================================

    def _log_performance_stats(self) -> None:
        """
        定期输出性能统计（每 stats_interval 秒）。

        统计指标：
          - FPS（实际处理帧率）
          - 平均推理延迟（ms）
          - 平均报警发布延迟（ms）
          - 报警发布总数
        """
        now = time.time()
        with self._stats_lock:
            elapsed = now - self._last_stats_time
            if elapsed < self._stats_interval:
                return
            self._last_stats_time = now

            if self._frame_count > 0:
                self._fps = self._frame_count / elapsed
                avg_inference_ms = (
                    self._total_inference_ms / self._frame_count
                )
                self.get_logger().info(
                    f"[性能] FPS: {self._fps:.1f} | "
                    f"平均推理: {avg_inference_ms:.1f}ms | "
                    f"处理帧数: {self._frame_count}"
                )
                if self._alarm_count > 0:
                    avg_alarm_ms = (
                        self._total_alarm_latency_ms / self._alarm_count
                    )
                    self.get_logger().info(
                        f"[性能] 报警发布: {self._alarm_count}条 | "
                        f"平均延迟: {avg_alarm_ms:.1f}ms"
                    )

            # 性能告警
            if self._fps > 0 and self._fps < 10.0:
                self.get_logger().warn(
                    f"[性能] FPS 低于目标 ({self._fps:.1f} < 10)！"
                    f"请检查模型和GPU状态"
                )
            avg_inf = (
                self._total_inference_ms / max(self._frame_count, 1)
            )
            if avg_inf > 60.0:
                self.get_logger().warn(
                    f"[性能] 推理延迟超标 "
                    f"({avg_inf:.1f}ms > 60ms)！"
                )

            # 重置计数器
            self._frame_count = 0
            self._total_inference_ms = 0.0
            self._total_alarm_latency_ms = 0.0
            self._alarm_count = 0

    # ========================================================
    # GPU 内存管理
    # ========================================================

    @staticmethod
    def _clear_gpu_cache() -> None:
        """清理 GPU 缓存以应对 OOM。"""
        try:
            import torch
            torch.cuda.empty_cache()
        except ImportError:
            pass
        try:
            import tensorrt as trt
            # TensorRT 无直接清理 API，依赖 torch 清理
        except ImportError:
            pass

    # ========================================================
    # 生命周期
    # ========================================================

    def shutdown(self) -> None:
        """优雅关闭：释放所有资源。"""
        self.get_logger().info("正在关闭推理节点...")
        self._running = False
        self._color_new.set()  # 唤醒推理线程使其退出

        # 等待推理线程退出
        if self._inference_thread.is_alive():
            self._inference_thread.join(timeout=5.0)

        # 释放模型
        if hasattr(self, "_model") and self._model is not None:
            del self._model
            self._model = None
        if hasattr(self, "_crack_model") and self._crack_model is not None:
            del self._crack_model
            self._crack_model = None

        # 清理 GPU
        self._clear_gpu_cache()

        self.get_logger().info("推理节点已关闭，资源已释放")


# ============================================================
# 入口
# ============================================================

def main(args=None):
    """节点入口函数（ros2 run 调用）。"""
    rclpy.init(args=args)
    node = YOLOv8InferenceNode()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        node.get_logger().info("收到键盘中断")
    except SystemExit:
        node.get_logger().error("系统退出")
    finally:
        node.shutdown()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
