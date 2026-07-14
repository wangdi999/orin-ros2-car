#!/usr/bin/env python3
"""Small HTTP gateway for safe manual motion through the real car arbiter.

The gateway intentionally publishes only to /cmd_vel_manual. The real
cmd_vel_arbiter remains the sole normal publisher on /cmd_vel.
"""

from __future__ import annotations

import argparse
import json
import math
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import rclpy
from geometry_msgs.msg import PoseWithCovarianceStamped, Twist
from nav2_msgs.action import NavigateToPose
from nav_msgs.msg import Odometry
from rclpy.action import ActionClient
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from std_msgs.msg import Bool, String

MAX_DISTANCE_M = 0.30
MAX_SPEED_MPS = 0.08
MAX_DURATION_SEC = 8.0


@dataclass(frozen=True)
class MotionLimits:
    max_distance_m: float = MAX_DISTANCE_M
    max_speed_mps: float = MAX_SPEED_MPS
    max_duration_sec: float = MAX_DURATION_SEC


class GatewayError(Exception):
    def __init__(self, status_code: int, payload: dict[str, Any]) -> None:
        super().__init__(payload.get("error_message", "gateway error"))
        self.status_code = status_code
        self.payload = payload


class MotionValidationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class MotionCommand:
    action: str
    direction: str | None = None
    linear_x: float = 0.0
    linear_y: float = 0.0
    angular_z: float = 0.0
    distance_m: float | None = None
    max_speed_mps: float | None = None
    duration_sec: float = 0.0
    reason: str = ""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_motion_payload(
    payload: dict[str, Any],
    *,
    limits: MotionLimits = MotionLimits(),
) -> MotionCommand:
    raw = payload.get("intent") if isinstance(payload.get("intent"), dict) else payload
    if not isinstance(raw, dict):
        raise MotionValidationError("INVALID_MOTION_PAYLOAD", "motion payload must be an object")

    action = str(raw.get("action") or "").strip().upper()
    if action == "STOP":
        return MotionCommand(action="STOP", reason=str(raw.get("reason") or ""))
    if action == "EMERGENCY_STOP":
        return MotionCommand(action="EMERGENCY_STOP", reason=str(raw.get("reason") or ""))
    if action != "MOVE":
        raise MotionValidationError("UNSUPPORTED_MOTION_ACTION", "unsupported motion action")

    direction = str(raw.get("direction") or "").strip().upper()
    if direction not in {"FORWARD", "BACKWARD", "LEFT", "RIGHT"}:
        raise MotionValidationError("INVALID_MOTION_DIRECTION", "unsupported motion direction")

    speed = _optional_float(raw.get("max_speed_mps"), default=0.05)
    if speed is None or speed <= 0.0:
        raise MotionValidationError("INVALID_MOTION_SPEED", "speed must be positive")
    if speed > limits.max_speed_mps:
        raise MotionValidationError(
            "MOTION_SPEED_TOO_HIGH",
            f"speed exceeds {limits.max_speed_mps:.2f} m/s",
        )

    distance = _optional_float(raw.get("distance_m"), default=None)
    duration = _optional_float(raw.get("duration_sec"), default=None)
    if distance is None and duration is None:
        raise MotionValidationError("MOTION_DISTANCE_REQUIRED", "distance or duration is required")
    if distance is not None:
        if distance <= 0.0:
            raise MotionValidationError("INVALID_MOTION_DISTANCE", "distance must be positive")
        if distance > limits.max_distance_m:
            raise MotionValidationError(
                "MOTION_DISTANCE_TOO_LONG",
                f"distance exceeds {limits.max_distance_m:.2f} m",
            )
    if duration is not None:
        if duration <= 0.0:
            raise MotionValidationError("INVALID_MOTION_DURATION", "duration must be positive")
        if duration > limits.max_duration_sec:
            raise MotionValidationError(
                "MOTION_DURATION_TOO_LONG",
                f"duration exceeds {limits.max_duration_sec:.1f} s",
            )

    if distance is not None:
        distance_duration = distance / speed
        duration = min(duration, distance_duration) if duration is not None else distance_duration
    assert duration is not None
    if duration > limits.max_duration_sec:
        raise MotionValidationError(
            "MOTION_DURATION_TOO_LONG",
            f"computed duration exceeds {limits.max_duration_sec:.1f} s",
        )
    if speed * duration > limits.max_distance_m + 1e-9:
        raise MotionValidationError(
            "MOTION_DISTANCE_TOO_LONG",
            f"speed and duration exceed {limits.max_distance_m:.2f} m travel limit",
        )

    linear_x, linear_y = _direction_to_velocity(direction, speed)
    return MotionCommand(
        action="MOVE",
        direction=direction,
        linear_x=linear_x,
        linear_y=linear_y,
        angular_z=0.0,
        distance_m=distance,
        max_speed_mps=speed,
        duration_sec=duration,
        reason=str(raw.get("reason") or ""),
    )


class AgentMotionGateway(Node):
    def __init__(self, *, motion_topic: str, stale_sec: float, limits: MotionLimits) -> None:
        super().__init__("agent_motion_gateway")
        self._motion_topic = motion_topic
        self._stale_sec = stale_sec
        self._limits = limits
        self._lock = threading.Lock()
        self._chassis_connected = False
        self._chassis_connected_at = 0.0
        self._safety_state = ""
        self._safety_state_at = 0.0
        self._patrol_status: dict[str, Any] | None = None
        self._patrol_status_at = 0.0
        self._pose: tuple[float, float, float] | None = None
        self._pose_at = 0.0
        self._odom_at = 0.0
        self._motion_lock = threading.Lock()
        self._motion_stop_event: threading.Event | None = None
        self._motion_thread: threading.Thread | None = None
        self._motion_command_id = 0

        self._motion_pub = self.create_publisher(Twist, self._motion_topic, 1)
        self._estop_pub = self.create_publisher(Bool, "/safety/estop", 10)
        self._nav_client = ActionClient(self, NavigateToPose, "/navigate_to_pose")
        self.create_subscription(Bool, "/chassis/connected", self._on_chassis, 10)
        self.create_subscription(String, "/safety/state", self._on_safety_state, 10)
        self.create_subscription(String, "/patrol/status", self._on_patrol_status, 10)
        self.create_subscription(Odometry, "/odom", self._on_odom, 10)
        self.create_subscription(PoseWithCovarianceStamped, "/amcl_pose", self._on_pose, 10)

    def get_summary(self) -> dict[str, Any]:
        now = time.monotonic()
        with self._lock:
            chassis_connected = (
                self._chassis_connected and now - self._chassis_connected_at <= self._stale_sec
            )
            safety_state = self._safety_state if now - self._safety_state_at <= self._stale_sec else ""
            patrol_status = (
                self._patrol_status if now - self._patrol_status_at <= self._stale_sec else None
            )
            pose = self._pose if now - self._pose_at <= self._stale_sec else None
            odom_fresh = now - self._odom_at <= self._stale_sec

        active_state = str((patrol_status or {}).get("state") or "IDLE")
        active_task_id = (patrol_status or {}).get("task_id")
        return {
            "gateway_online": True,
            "chassis_online": chassis_connected or odom_fresh or self._topic_has_publishers("/odom"),
            "lidar_online": self._topic_has_publishers("/scan"),
            "camera_online": self._topic_has_publishers("/image_raw")
            or self._topic_has_publishers("/camera/image_raw"),
            "nav2_ready": self._nav_client.server_is_ready(),
            "yolo_online": self._topic_has_publishers("/alarm_events"),
            "emergency_stopped": "ESTOP" in safety_state.upper()
            or "EMERGENCY" in safety_state.upper(),
            "active_task_id": active_task_id if active_task_id else None,
            "active_task_state": active_state,
            "current_waypoint_index": int((patrol_status or {}).get("current_index") or 0),
            "current_location_id": (patrol_status or {}).get("current_location_id"),
            "pose_x": pose[0] if pose else None,
            "pose_y": pose[1] if pose else None,
            "pose_yaw": pose[2] if pose else None,
            "last_update": utc_now(),
            "safety_state": safety_state,
            "motion_topic": self._motion_topic,
            "motion_subscribers": len(self.get_subscriptions_info_by_topic(self._motion_topic)),
            "cmd_vel_publishers": len(self.get_publishers_info_by_topic("/cmd_vel")),
            "motion_limits": {
                "max_distance_m": self._limits.max_distance_m,
                "max_speed_mps": self._limits.max_speed_mps,
                "max_duration_sec": self._limits.max_duration_sec,
            },
        }

    def set_emergency_stop(self, active: bool, reason: str = "") -> dict[str, Any]:
        del reason
        if active:
            self._stop_motion()
        message = Bool()
        message.data = bool(active)
        self._estop_pub.publish(message)
        return {"success": True, "active": bool(active)}

    def execute_motion(self, payload: dict[str, Any]) -> dict[str, Any]:
        command = normalize_motion_payload(payload, limits=self._limits)
        if command.action == "EMERGENCY_STOP":
            result = self.set_emergency_stop(True, command.reason)
            return {"accepted": True, "state": "EMERGENCY_STOPPED", **result}
        if command.action == "STOP":
            self._stop_motion()
            return {"accepted": True, "state": "STOPPED"}

        summary = self.get_summary()
        if summary.get("emergency_stopped"):
            raise GatewayError(
                409,
                {
                    "error_code": "ROBOT_ESTOPPED",
                    "error_message": "emergency stop is active",
                },
            )
        if not summary.get("chassis_online"):
            raise GatewayError(
                409,
                {
                    "error_code": "CHASSIS_OFFLINE",
                    "error_message": "chassis bridge is not online",
                },
            )
        if int(summary.get("motion_subscribers") or 0) < 1:
            raise GatewayError(
                409,
                {
                    "error_code": "MANUAL_ARBITER_OFFLINE",
                    "error_message": "no subscriber on manual motion topic",
                },
            )
        if int(summary.get("cmd_vel_publishers") or 0) != 1:
            raise GatewayError(
                409,
                {
                    "error_code": "CMD_VEL_BOUNDARY_UNSAFE",
                    "error_message": "cmd_vel must have exactly one publisher",
                },
            )

        command_id = self._start_motion(command)
        return {
            "accepted": True,
            "state": "RUNNING",
            "command_id": command_id,
            "duration_sec": command.duration_sec,
            "motion_topic": self._motion_topic,
            "twist": {
                "linear": {"x": command.linear_x, "y": command.linear_y, "z": 0.0},
                "angular": {"x": 0.0, "y": 0.0, "z": command.angular_z},
            },
        }

    def _start_motion(self, command: MotionCommand) -> int:
        with self._motion_lock:
            if self._motion_thread is not None and self._motion_thread.is_alive():
                raise GatewayError(
                    409,
                    {
                        "error_code": "MOTION_ALREADY_RUNNING",
                        "error_message": "a motion command is already running",
                    },
                )
            self._motion_command_id += 1
            command_id = self._motion_command_id
            stop_event = threading.Event()
            thread = threading.Thread(
                target=self._run_motion,
                args=(command_id, command, stop_event),
                daemon=True,
            )
            self._motion_stop_event = stop_event
            self._motion_thread = thread
            thread.start()
            return command_id

    def _stop_motion(self) -> None:
        with self._motion_lock:
            if self._motion_stop_event is not None:
                self._motion_stop_event.set()
            self._publish_zero_burst()

    def _run_motion(
        self,
        command_id: int,
        command: MotionCommand,
        stop_event: threading.Event,
    ) -> None:
        twist = Twist()
        twist.linear.x = command.linear_x
        twist.linear.y = command.linear_y
        twist.angular.z = command.angular_z
        deadline = time.monotonic() + command.duration_sec
        try:
            while rclpy.ok() and not stop_event.is_set() and time.monotonic() < deadline:
                self._motion_pub.publish(twist)
                time.sleep(0.05)
        finally:
            self._publish_zero_burst()
            with self._motion_lock:
                if command_id == self._motion_command_id:
                    self._motion_stop_event = None
                    self._motion_thread = None

    def _publish_zero_burst(self) -> None:
        zero = Twist()
        for _ in range(5):
            self._motion_pub.publish(zero)
            time.sleep(0.02)

    def _on_chassis(self, message: Bool) -> None:
        with self._lock:
            self._chassis_connected = bool(message.data)
            self._chassis_connected_at = time.monotonic()

    def _on_safety_state(self, message: String) -> None:
        with self._lock:
            self._safety_state = str(message.data)
            self._safety_state_at = time.monotonic()

    def _on_patrol_status(self, message: String) -> None:
        try:
            status = json.loads(message.data)
        except (TypeError, ValueError, json.JSONDecodeError):
            status = {"state": str(message.data or "UNKNOWN")}
        if not isinstance(status, dict):
            status = {"state": "UNKNOWN"}
        with self._lock:
            self._patrol_status = status
            self._patrol_status_at = time.monotonic()

    def _on_odom(self, _message: Odometry) -> None:
        with self._lock:
            self._odom_at = time.monotonic()

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


class GatewayRequestHandler(BaseHTTPRequestHandler):
    server_version = "AgentMotionGateway/0.1"

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
            if self.path == "/api/v1/motion/execute":
                self._send_json(200, self._node().execute_motion(self._json_body()))
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
            if self.path in {"/api/v1/patrol/create", "/api/v1/patrol/control"}:
                self._send_json(
                    501,
                    {
                        "accepted": False,
                        "success": False,
                        "error_code": "PATROL_HTTP_GATEWAY_NOT_IMPLEMENTED",
                        "error_message": "real patrol services use the native icar_navigation API",
                    },
                )
                return
            self._send_json(404, {"error_code": "NOT_FOUND"})
        except GatewayError as exc:
            self._send_json(exc.status_code, exc.payload)
        except MotionValidationError as exc:
            self._send_json(422, {"error_code": exc.code, "error_message": exc.message})
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

    def _node(self) -> AgentMotionGateway:
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


def _optional_float(value: Any, *, default: float | None) -> float | None:
    if value is None or value == "":
        return default
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise MotionValidationError("INVALID_MOTION_NUMBER", "motion number is invalid") from exc
    if not math.isfinite(number):
        raise MotionValidationError("INVALID_MOTION_NUMBER", "motion number must be finite")
    return number


def _direction_to_velocity(direction: str, speed: float) -> tuple[float, float]:
    if direction == "FORWARD":
        return speed, 0.0
    if direction == "BACKWARD":
        return -speed, 0.0
    if direction == "LEFT":
        return 0.0, speed
    if direction == "RIGHT":
        return 0.0, -speed
    raise MotionValidationError("INVALID_MOTION_DIRECTION", "unsupported motion direction")


def _yaw_from_quaternion(x: float, y: float, z: float, w: float) -> float:
    siny_cosp = 2.0 * (w * z + x * y)
    cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
    return math.atan2(siny_cosp, cosy_cosp)


def _serve_http(
    node: AgentMotionGateway,
    *,
    host: str,
    port: int,
    stop_event: threading.Event,
) -> None:
    server = ThreadingHTTPServer((host, port), GatewayRequestHandler)
    server.gateway_node = node  # type: ignore[attr-defined]
    server.timeout = 0.5
    node.get_logger().info("Agent motion gateway listening on %s:%s" % (host, port))
    while not stop_event.is_set():
        server.handle_request()
    server.server_close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8130)
    parser.add_argument("--motion-topic", default="/cmd_vel_manual")
    parser.add_argument("--stale-sec", type=float, default=3.0)
    parser.add_argument("--max-distance-m", type=float, default=MAX_DISTANCE_M)
    parser.add_argument("--max-speed-mps", type=float, default=MAX_SPEED_MPS)
    parser.add_argument("--max-duration-sec", type=float, default=MAX_DURATION_SEC)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rclpy.init()
    limits = MotionLimits(
        max_distance_m=args.max_distance_m,
        max_speed_mps=args.max_speed_mps,
        max_duration_sec=args.max_duration_sec,
    )
    if min(limits.max_distance_m, limits.max_speed_mps, limits.max_duration_sec) <= 0:
        raise SystemExit("motion limits must be positive")
    node = AgentMotionGateway(
        motion_topic=args.motion_topic,
        stale_sec=args.stale_sec,
        limits=limits,
    )
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    stop_event = threading.Event()
    http_thread = threading.Thread(
        target=_serve_http,
        args=(node,),
        kwargs={"host": args.host, "port": args.port, "stop_event": stop_event},
        daemon=True,
    )
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
