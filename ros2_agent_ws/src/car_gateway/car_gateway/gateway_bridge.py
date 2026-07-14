from __future__ import annotations

import argparse
import json
import math
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import rclpy
from car_interfaces.msg import PatrolStatus
from car_interfaces.srv import ControlPatrol, CreatePatrol
from geometry_msgs.msg import PoseWithCovarianceStamped
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from std_msgs.msg import Bool


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class GatewayBridgeNode(Node):
    def __init__(self) -> None:
        super().__init__("agent_http_gateway_bridge")
        self.declare_parameter("http_host", "127.0.0.1")
        self.declare_parameter("http_port", 8130)
        self.declare_parameter("service_timeout_sec", 3.0)
        self.declare_parameter("status_stale_sec", 3.0)
        self.declare_parameter("nav_action_name", "navigate_to_pose")

        self._service_timeout_sec = float(self.get_parameter("service_timeout_sec").value)
        self._status_stale_sec = float(self.get_parameter("status_stale_sec").value)
        self._lock = threading.Lock()
        self._patrol_status: PatrolStatus | None = None
        self._patrol_status_at = 0.0
        self._emergency_stopped = False
        self._pose: tuple[float, float, float] | None = None
        self._pose_at = 0.0

        self._create_client = self.create_client(CreatePatrol, "/patrol/create")
        self._control_client = self.create_client(ControlPatrol, "/patrol/control")
        self._estop_pub = self.create_publisher(Bool, "/safety/emergency_stop", 10)
        self.create_subscription(PatrolStatus, "/patrol/status", self._on_patrol_status, 20)
        self.create_subscription(Bool, "/safety/emergency_stop", self._on_emergency_stop, 20)
        self.create_subscription(
            PoseWithCovarianceStamped,
            "/amcl_pose",
            self._on_pose,
            10,
        )

    @property
    def http_host(self) -> str:
        return str(self.get_parameter("http_host").value)

    @property
    def http_port(self) -> int:
        return int(self.get_parameter("http_port").value)

    def get_summary(self) -> dict[str, Any]:
        now = time.monotonic()
        with self._lock:
            status = self._patrol_status
            status_fresh = status is not None and now - self._patrol_status_at <= self._status_stale_sec
            pose = self._pose if now - self._pose_at <= self._status_stale_sec else None
            emergency_stopped = self._emergency_stopped

        active_task_id = status.task_id if status_fresh and status and status.task_id else None
        active_state = status.state if status_fresh and status and status.state else "IDLE"
        nav_status = status.nav_status if status_fresh and status else ""
        return {
            "gateway_online": True,
            "chassis_online": self._chassis_online(),
            "lidar_online": self._topic_has_publishers("/scan"),
            "camera_online": self._topic_has_publishers("/image_raw")
            or self._topic_has_publishers("/camera/image_raw"),
            "nav2_ready": self._action_server_present(
                str(self.get_parameter("nav_action_name").value)
            ),
            "yolo_online": self._topic_has_publishers("/alarm_events"),
            "emergency_stopped": emergency_stopped,
            "active_task_id": active_task_id,
            "active_task_state": active_state,
            "current_waypoint_index": int(status.current_index if status_fresh and status else 0),
            "current_location_id": (
                status.current_location_id if status_fresh and status.current_location_id else None
            ),
            "pose_x": pose[0] if pose else None,
            "pose_y": pose[1] if pose else None,
            "pose_yaw": pose[2] if pose else None,
            "last_update": utc_now(),
            "nav_status": nav_status,
            "patrol_status_fresh": status_fresh,
        }

    def create_patrol(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = CreatePatrol.Request()
        request.task_id = str(payload.get("task_id") or "")
        request.name = str(payload.get("name") or request.task_id)
        request.location_ids = [str(item) for item in payload.get("location_ids", [])]
        event_policy = payload.get("event_policy", {})
        request.event_policy_json = json.dumps(
            event_policy if isinstance(event_policy, dict) else {},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        request.return_home = bool(payload.get("return_home", False))

        response = self._call_service(self._create_client, request, "CREATE_PATROL_UNAVAILABLE")
        return {
            "accepted": bool(response.accepted),
            "error_code": response.error_code,
            "error_message": response.error_message,
        }

    def control_patrol(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = ControlPatrol.Request()
        request.task_id = str(payload.get("task_id") or "")
        request.operation = str(payload.get("operation") or "").upper()
        request.reason = str(payload.get("reason") or "")

        response = self._call_service(self._control_client, request, "CONTROL_PATROL_UNAVAILABLE")
        return {
            "success": bool(response.success),
            "state": response.state,
            "error_code": response.error_code,
            "error_message": response.error_message,
        }

    def set_emergency_stop(self, active: bool, reason: str = "") -> dict[str, Any]:
        del reason
        message = Bool()
        message.data = bool(active)
        self._estop_pub.publish(message)
        with self._lock:
            self._emergency_stopped = bool(active)
        return {"success": True, "active": bool(active)}

    def _call_service(self, client, request, unavailable_code: str):
        if not client.wait_for_service(timeout_sec=self._service_timeout_sec):
            raise GatewayError(
                503,
                {
                    "error_code": unavailable_code,
                    "error_message": "ROS service is unavailable",
                },
            )
        future = client.call_async(request)
        deadline = time.monotonic() + self._service_timeout_sec
        while rclpy.ok() and not future.done() and time.monotonic() < deadline:
            time.sleep(0.01)
        if not future.done() or future.result() is None:
            raise GatewayError(
                504,
                {
                    "error_code": "ROS_SERVICE_TIMEOUT",
                    "error_message": unavailable_code,
                },
            )
        return future.result()

    def _on_patrol_status(self, message: PatrolStatus) -> None:
        with self._lock:
            self._patrol_status = message
            self._patrol_status_at = time.monotonic()

    def _on_emergency_stop(self, message: Bool) -> None:
        with self._lock:
            self._emergency_stopped = bool(message.data)

    def _on_pose(self, message: PoseWithCovarianceStamped) -> None:
        pose = message.pose.pose
        with self._lock:
            self._pose = (
                float(pose.position.x),
                float(pose.position.y),
                _yaw_from_quaternion(
                    pose.orientation.x,
                    pose.orientation.y,
                    pose.orientation.z,
                    pose.orientation.w,
                ),
            )
            self._pose_at = time.monotonic()

    def _topic_has_publishers(self, topic: str) -> bool:
        return bool(self.get_publishers_info_by_topic(topic))

    def _topic_has_subscribers(self, topic: str) -> bool:
        return bool(self.get_subscriptions_info_by_topic(topic))

    def _chassis_online(self) -> bool:
        return (
            self._topic_has_subscribers("/cmd_vel")
            or self._topic_has_publishers("/odom")
            or self._topic_has_publishers("/odom_raw")
        )

    def _action_server_present(self, action_name: str) -> bool:
        prefix = "/" + action_name.strip("/")
        services = {name for name, _ in self.get_service_names_and_types()}
        required = {
            f"{prefix}/_action/send_goal",
            f"{prefix}/_action/get_result",
            f"{prefix}/_action/cancel_goal",
        }
        return required.issubset(services)


class GatewayError(Exception):
    def __init__(self, status_code: int, payload: dict[str, Any]) -> None:
        super().__init__(payload.get("error_message", "gateway error"))
        self.status_code = status_code
        self.payload = payload


class GatewayRequestHandler(BaseHTTPRequestHandler):
    server_version = "CarGatewayBridge/0.1"

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send_json(200, {"ok": True, "summary": self._node().get_summary()})
            return
        if self.path == "/api/v1/robot/summary":
            self._send_json(200, self._node().get_summary())
            return
        self._send_json(404, {"error_code": "NOT_FOUND"})

    def do_POST(self) -> None:
        try:
            if self.path == "/api/v1/patrol/create":
                self._send_json(200, self._node().create_patrol(self._json_body()))
                return
            if self.path == "/api/v1/patrol/control":
                self._send_json(200, self._node().control_patrol(self._json_body()))
                return
            if self.path == "/api/v1/safety/emergency-stop":
                payload = self._json_body()
                self._send_json(
                    200,
                    self._node().set_emergency_stop(
                        bool(payload.get("active", True)),
                        str(payload.get("reason") or ""),
                    ),
                )
                return
            self._send_json(404, {"error_code": "NOT_FOUND"})
        except GatewayError as exc:
            self._send_json(exc.status_code, exc.payload)
        except ValueError as exc:
            self._send_json(400, {"error_code": "BAD_REQUEST", "error_message": str(exc)})

    def log_message(self, format: str, *args: Any) -> None:
        self._node().get_logger().info("%s - %s" % (self.address_string(), format % args))

    def _json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 65536:
            raise ValueError("invalid JSON request size")
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object")
        return payload

    def _node(self) -> GatewayBridgeNode:
        node = getattr(self.server, "gateway_node", None)
        if node is None:
            raise RuntimeError("gateway node not attached")
        return node

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def _yaw_from_quaternion(x: float, y: float, z: float, w: float) -> float:
    siny_cosp = 2.0 * (w * z + x * y)
    cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
    return math.atan2(siny_cosp, cosy_cosp)


def _serve_http(node: GatewayBridgeNode, stop_event: threading.Event) -> None:
    server = ThreadingHTTPServer((node.http_host, node.http_port), GatewayRequestHandler)
    server.gateway_node = node  # type: ignore[attr-defined]
    server.timeout = 0.5
    node.get_logger().info(f"Agent HTTP gateway listening on {node.http_host}:{node.http_port}")
    while not stop_event.is_set():
        server.handle_request()
    server.server_close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ros-args", nargs="*")
    return parser.parse_args()


def main(args=None) -> None:
    del args
    rclpy.init()
    node = GatewayBridgeNode()
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    stop_event = threading.Event()
    http_thread = threading.Thread(target=_serve_http, args=(node, stop_event), daemon=True)
    http_thread.start()
    try:
        executor.spin()
    finally:
        stop_event.set()
        http_thread.join(timeout=2.0)
        executor.shutdown()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
