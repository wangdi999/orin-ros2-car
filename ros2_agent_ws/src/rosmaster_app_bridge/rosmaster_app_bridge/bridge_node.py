from __future__ import annotations

import json
import socket
import time

import rclpy
from geometry_msgs.msg import Twist
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import Bool, String

from .protocol import encode_motion_packet, resolve_app_host, sanitize_velocity


def monotonic_ms() -> int:
    return int(time.monotonic() * 1000)


class RosmasterAppBridge(Node):
    def __init__(self) -> None:
        super().__init__("rosmaster_app_bridge")
        self.declare_parameter("app_host", "127.0.0.1")
        self.declare_parameter("app_port", 6000)
        self.declare_parameter("car_type", 1)
        self.declare_parameter("cmd_vel_topic", "/cmd_vel")
        self.declare_parameter("connected_topic", "/chassis/connected")
        self.declare_parameter("status_topic", "/chassis/status")
        self.declare_parameter("allowed_cmd_vel_publishers", ["safety_supervisor"])
        self.declare_parameter("max_linear_x", 0.08)
        self.declare_parameter("max_linear_y", 0.08)
        self.declare_parameter("max_angular_z", 0.0)
        self.declare_parameter("deadband_linear", 0.005)
        self.declare_parameter("watchdog_timeout_ms", 350)
        self.declare_parameter("output_hz", 20.0)
        self.declare_parameter("connect_timeout_sec", 1.0)
        self.declare_parameter("reconnect_period_sec", 1.0)

        self._host = resolve_app_host(
            str(self.get_parameter("app_host").value),
            port=int(self.get_parameter("app_port").value),
        )
        self._port = int(self.get_parameter("app_port").value)
        self._car_type = int(self.get_parameter("car_type").value)
        self._cmd_vel_topic = str(self.get_parameter("cmd_vel_topic").value)
        self._allowed_publishers = {
            str(item).strip("/")
            for item in self.get_parameter("allowed_cmd_vel_publishers").value
        }
        self._max_linear_x = float(self.get_parameter("max_linear_x").value)
        self._max_linear_y = float(self.get_parameter("max_linear_y").value)
        self._max_angular_z = float(self.get_parameter("max_angular_z").value)
        self._deadband_linear = float(self.get_parameter("deadband_linear").value)
        self._watchdog_timeout_ms = int(self.get_parameter("watchdog_timeout_ms").value)
        self._connect_timeout_sec = float(self.get_parameter("connect_timeout_sec").value)
        self._reconnect_period_sec = float(self.get_parameter("reconnect_period_sec").value)
        output_hz = float(self.get_parameter("output_hz").value)

        self._socket: socket.socket | None = None
        self._last_connect_attempt = 0.0
        self._last_cmd_at_ms: int | None = None
        self._last_packet = encode_motion_packet(car_type=self._car_type, linear_x=0.0, linear_y=0.0)
        self._last_sent_packet: bytes | None = None
        self._last_error = ""
        self._accepted_messages = 0
        self._rejected_messages = 0
        self._source_ok = False

        connected_qos = QoSProfile(depth=1)
        connected_qos.reliability = ReliabilityPolicy.RELIABLE
        connected_qos.durability = DurabilityPolicy.TRANSIENT_LOCAL
        self._connected_pub = self.create_publisher(
            Bool, str(self.get_parameter("connected_topic").value), connected_qos
        )
        self._status_pub = self.create_publisher(
            String, str(self.get_parameter("status_topic").value), 10
        )
        self.create_subscription(Twist, self._cmd_vel_topic, self._on_cmd_vel, 10)
        self.create_timer(1.0 / max(output_hz, 1.0), self._tick)
        self.get_logger().info(
            f"Rosmaster App bridge ready: {self._cmd_vel_topic} -> {self._host}:{self._port}, "
            f"limits=({self._max_linear_x:.3f},{self._max_linear_y:.3f},{self._max_angular_z:.3f})"
        )

    def _on_cmd_vel(self, msg: Twist) -> None:
        if not self._cmd_vel_source_is_allowed():
            self._rejected_messages += 1
            self._source_ok = False
            self._last_error = "CMD_VEL_SOURCE_NOT_ALLOWED"
            self._last_packet = encode_motion_packet(
                car_type=self._car_type,
                linear_x=0.0,
                linear_y=0.0,
            )
            return
        self._source_ok = True
        velocity = sanitize_velocity(
            msg.linear.x,
            msg.linear.y,
            msg.angular.z,
            max_linear_x=self._max_linear_x,
            max_linear_y=self._max_linear_y,
            max_angular_z=self._max_angular_z,
            deadband_linear=self._deadband_linear,
        )
        if velocity is None:
            self._rejected_messages += 1
            self._last_error = "NON_FINITE_CMD_VEL"
            self._last_packet = encode_motion_packet(
                car_type=self._car_type,
                linear_x=0.0,
                linear_y=0.0,
            )
            return
        linear_x, linear_y, angular_z = velocity
        if angular_z:
            self._last_error = "ANGULAR_Z_IGNORED_BY_APP_PROTOCOL"
        else:
            self._last_error = ""
        self._last_packet = encode_motion_packet(
            car_type=self._car_type,
            linear_x=linear_x,
            linear_y=linear_y,
        )
        self._last_cmd_at_ms = monotonic_ms()
        self._accepted_messages += 1

    def _tick(self) -> None:
        if not self._ensure_connected():
            self._publish_status(False)
            return

        packet = self._last_packet
        if self._last_cmd_at_ms is None:
            packet = encode_motion_packet(car_type=self._car_type, linear_x=0.0, linear_y=0.0)
        elif monotonic_ms() - self._last_cmd_at_ms > self._watchdog_timeout_ms:
            packet = encode_motion_packet(car_type=self._car_type, linear_x=0.0, linear_y=0.0)
            self._last_error = "WATCHDOG_STOP"

        try:
            assert self._socket is not None
            self._socket.sendall(packet)
            self._last_sent_packet = packet
            self._publish_status(True)
        except OSError as exc:
            self._disconnect(str(exc))
            self._publish_status(False)

    def _cmd_vel_source_is_allowed(self) -> bool:
        if not self._allowed_publishers:
            return True
        publishers = self.get_publishers_info_by_topic(self._cmd_vel_topic)
        names = {item.node_name.strip("/") for item in publishers}
        return bool(names) and names.issubset(self._allowed_publishers)

    def _ensure_connected(self) -> bool:
        if self._socket is not None:
            return True
        now = time.monotonic()
        if now - self._last_connect_attempt < self._reconnect_period_sec:
            return False
        self._last_connect_attempt = now
        try:
            sock = socket.create_connection(
                (self._host, self._port),
                timeout=self._connect_timeout_sec,
            )
            sock.settimeout(self._connect_timeout_sec)
        except OSError as exc:
            self._last_error = f"CONNECT_FAILED:{exc}"
            return False
        self._socket = sock
        self._last_error = ""
        self.get_logger().info(f"Connected to Rosmaster App at {self._host}:{self._port}")
        return True

    def _disconnect(self, error: str) -> None:
        self._last_error = f"SEND_FAILED:{error}"
        if self._socket is not None:
            try:
                self._socket.close()
            except OSError:
                pass
        self._socket = None

    def _publish_status(self, connected: bool) -> None:
        connected_msg = Bool()
        connected_msg.data = bool(connected)
        self._connected_pub.publish(connected_msg)

        status_msg = String()
        status_msg.data = json.dumps(
            {
                "connected": bool(connected),
                "trusted_cmd_vel_source": bool(self._source_ok),
                "app_host": self._host,
                "app_port": self._port,
                "accepted_messages": self._accepted_messages,
                "rejected_messages": self._rejected_messages,
                "last_error": self._last_error,
                "last_sent_packet": (
                    self._last_sent_packet.decode("utf-8") if self._last_sent_packet else None
                ),
            },
            separators=(",", ":"),
        )
        self._status_pub.publish(status_msg)

    def destroy_node(self):
        try:
            if self._socket is not None:
                self._socket.sendall(
                    encode_motion_packet(car_type=self._car_type, linear_x=0.0, linear_y=0.0)
                )
        except OSError:
            pass
        if self._socket is not None:
            self._socket.close()
            self._socket = None
        return super().destroy_node()


def main(args=None) -> None:
    rclpy.init(args=args)
    node = RosmasterAppBridge()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
