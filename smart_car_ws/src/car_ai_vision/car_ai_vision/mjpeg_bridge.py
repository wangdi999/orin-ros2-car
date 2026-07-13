"""
MJPEG → ROS2 图像桥接节点 (requests版)。

从 Docker 容器内的 MJPEG 视频流读取帧，发布为 ROS2 Image 消息。

用法:
  source /opt/ros/foxy/setup.bash
  ros2 run car_ai_vision mjpeg_bridge --ros-args -p url:=http://localhost:6500/video_feed
"""
import io
import time
from typing import Optional

import cv2
import numpy as np
import requests

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from cv_bridge import CvBridge


class MjpegBridgeNode(Node):
    """从 MJPEG HTTP 流抓取帧并发布到 ROS2 Image 话题。"""

    def __init__(self):
        super().__init__("mjpeg_bridge")

        self.declare_parameter("url", "http://localhost:6500/video_feed")
        self.declare_parameter("fps", 15.0)
        self.declare_parameter("width", 640)
        self.declare_parameter("height", 480)

        url = self.get_parameter("url").value
        self._fps = self.get_parameter("fps").value
        self._width = self.get_parameter("width").value
        self._height = self.get_parameter("height").value

        self._bridge = CvBridge()
        self._pub = self.create_publisher(Image, "/camera/color/image_raw", 10)

        self.get_logger().info(f"连接 MJPEG 流: {url}")
        try:
            self._stream = requests.get(url, stream=True, timeout=(3.0, 60.0))
            if self._stream.status_code != 200:
                raise RuntimeError(f"HTTP {self._stream.status_code}")
            ct = self._stream.headers.get("Content-Type", "")
            self.get_logger().info(f"已连接, Content-Type: {ct}")
        except Exception as e:
            self.get_logger().error(f"无法连接 MJPEG 流: {e}")
            raise

        # 提取 multipart boundary
        self._boundary = None
        if "multipart" in ct.lower():
            for part in ct.split(";"):
                part = part.strip()
                if part.startswith("boundary="):
                    self._boundary = part[9:].encode()
                    self.get_logger().info(f"Boundary: {self._boundary}")

        self._buf = b""
        self._timer = self.create_timer(1.0 / max(self._fps, 1.0), self._process)

    def _process(self):
        """读取流数据并提取 JPEG 帧。"""
        try:
            # 小chunk读取，避免MJPEG流阻塞
            chunk = self._stream.raw.read(8192)
            if not chunk:
                return
            self._buf += chunk

            # 按 boundary 分割 multipart
            if self._boundary:
                bnd = self._boundary
                while True:
                    idx = self._buf.find(bnd)
                    if idx < 0:
                        break
                    start = self._buf.find(b"\r\n\r\n", idx)
                    if start < 0:
                        start = self._buf.find(b"\n\n", idx)
                    if start < 0:
                        break
                    start += 4
                    next_bnd = self._buf.find(bnd, start)
                    if next_bnd < 0:
                        break
                    jpeg = self._buf[start:next_bnd].rstrip(b"\r\n")
                    self._buf = self._buf[next_bnd:]
                    if len(jpeg) > 100:
                        self._publish_jpeg(jpeg)
            else:
                soi = self._buf.find(b"\xff\xd8")
                eoi = self._buf.find(b"\xff\xd9", soi) if soi >= 0 else -1
                if soi >= 0 and eoi > soi:
                    jpeg = self._buf[soi:eoi + 2]
                    self._buf = self._buf[eoi + 2:]
                    if len(jpeg) > 100:
                        self._publish_jpeg(jpeg)

            if len(self._buf) > 2_000_000:
                self._buf = self._buf[-500_000:]

        except Exception as e:
            self.get_logger().error(f"读取异常: {e}", throttle_duration_sec=5.0)
            # 重连
            try:
                self._stream.close()
                self._stream = requests.get(
                    self.get_parameter("url").value,
                    stream=True, timeout=(3.0, 60.0)
                )
                self._buf = b""
                self.get_logger().info("MJPEG 流已重连")
            except Exception:
                pass

    def _publish_jpeg(self, jpeg_data: bytes):
        """将 JPEG 字节流转为 ROS Image 并发布。"""
        try:
            arr = np.frombuffer(jpeg_data, np.uint8)
            frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if frame is None:
                return
            h, w = frame.shape[:2]
            if w != self._width or h != self._height:
                frame = cv2.resize(frame, (self._width, self._height))
            msg = self._bridge.cv2_to_imgmsg(frame, encoding="bgr8")
            msg.header.stamp = self.get_clock().now().to_msg()
            msg.header.frame_id = "camera_color_frame"
            msg.height = self._height
            msg.width = self._width
            self._pub.publish(msg)
        except Exception:
            pass  # 单帧解码失败不阻塞

    def shutdown(self):
        if hasattr(self, "_stream") and self._stream:
            self._stream.close()


def main(args=None):
    rclpy.init(args=args)
    node = MjpegBridgeNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.shutdown()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
