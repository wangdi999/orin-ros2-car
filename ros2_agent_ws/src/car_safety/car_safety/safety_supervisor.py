from __future__ import annotations

import json
import time

import rclpy
from car_interfaces.msg import PatrolStatus
from geometry_msgs.msg import Twist
from rclpy.node import Node
from std_msgs.msg import Bool, String

from .arbiter import Limits, Velocity, choose_velocity, sanitize


def monotonic_ms() -> int:
    return int(time.monotonic() * 1000)


class SafetySupervisor(Node):
    def __init__(self) -> None:
        super().__init__("safety_supervisor")
        self.declare_parameter("max_linear_x", 0.10)
        self.declare_parameter("max_linear_y", 0.10)
        self.declare_parameter("max_angular_z", 0.30)
        self.declare_parameter("teleop_timeout_ms", 450)
        self.declare_parameter("nav_timeout_ms", 500)
        self.declare_parameter("output_hz", 20.0)

        self._limits = Limits(
            max_linear_x=float(self.get_parameter("max_linear_x").value),
            max_linear_y=float(self.get_parameter("max_linear_y").value),
            max_angular_z=float(self.get_parameter("max_angular_z").value),
        )
        self._teleop_timeout_ms = int(self.get_parameter("teleop_timeout_ms").value)
        self._nav_timeout_ms = int(self.get_parameter("nav_timeout_ms").value)
        output_hz = float(self.get_parameter("output_hz").value)

        self._emergency_stopped = False
        self._patrol_running = False
        self._teleop = Velocity()
        self._navigation = Velocity()
        self._teleop_at_ms: int | None = None
        self._navigation_at_ms: int | None = None
        self._source = "ZERO"

        self._cmd_pub = self.create_publisher(Twist, "/cmd_vel", 10)
        self._state_pub = self.create_publisher(String, "/safety/state", 10)
        self.create_subscription(Twist, "/cmd_vel_teleop", self._on_teleop, 10)
        self.create_subscription(Twist, "/cmd_vel_nav", self._on_navigation, 10)
        self.create_subscription(Bool, "/safety/emergency_stop", self._on_emergency_stop, 10)
        self.create_subscription(PatrolStatus, "/patrol/status", self._on_patrol_status, 10)
        self.create_timer(1.0 / max(output_hz, 1.0), self._tick)
        self.get_logger().info(
            "Safety Supervisor ready: EMERGENCY_STOP > MANUAL_TELEOP > NAVIGATION > ZERO"
        )

    def _on_teleop(self, msg: Twist) -> None:
        value = sanitize(self._from_twist(msg), self._limits)
        if value is None:
            self.get_logger().error("Rejected non-finite teleop command; forcing zero")
            self._teleop = Velocity()
            self._teleop_at_ms = None
            return
        self._teleop = value
        self._teleop_at_ms = monotonic_ms()

    def _on_navigation(self, msg: Twist) -> None:
        value = sanitize(self._from_twist(msg), self._limits)
        if value is None:
            self.get_logger().error("Rejected non-finite navigation command; forcing zero")
            self._navigation = Velocity()
            self._navigation_at_ms = None
            return
        self._navigation = value
        self._navigation_at_ms = monotonic_ms()

    def _on_emergency_stop(self, msg: Bool) -> None:
        self._emergency_stopped = bool(msg.data)
        if self._emergency_stopped:
            self._teleop_at_ms = None
            self._navigation_at_ms = None
            self._publish_zero_burst()
            self.get_logger().warn("Emergency stop latched")
        else:
            self.get_logger().warn("Emergency stop explicitly cleared")

    def _on_patrol_status(self, msg: PatrolStatus) -> None:
        self._patrol_running = msg.state == "RUNNING"

    def _tick(self) -> None:
        source, selected = choose_velocity(
            emergency_stopped=self._emergency_stopped,
            now_ms=monotonic_ms(),
            teleop=self._teleop,
            teleop_at_ms=self._teleop_at_ms,
            teleop_timeout_ms=self._teleop_timeout_ms,
            navigation=self._navigation,
            navigation_at_ms=self._navigation_at_ms,
            navigation_timeout_ms=self._nav_timeout_ms,
            patrol_running=self._patrol_running,
        )
        safe = sanitize(selected, self._limits) or Velocity()
        self._cmd_pub.publish(self._to_twist(safe))
        if source != self._source:
            self._source = source
            self._publish_state()

    def _publish_state(self) -> None:
        msg = String()
        msg.data = json.dumps(
            {
                "source": self._source,
                "emergency_stopped": self._emergency_stopped,
                "patrol_running": self._patrol_running,
                "limits": {
                    "linear_x": self._limits.max_linear_x,
                    "linear_y": self._limits.max_linear_y,
                    "angular_z": self._limits.max_angular_z,
                },
            },
            separators=(",", ":"),
        )
        self._state_pub.publish(msg)

    def _publish_zero_burst(self) -> None:
        zero = Twist()
        for _ in range(3):
            self._cmd_pub.publish(zero)

    @staticmethod
    def _from_twist(msg: Twist) -> Velocity:
        return Velocity(msg.linear.x, msg.linear.y, msg.angular.z)

    @staticmethod
    def _to_twist(value: Velocity) -> Twist:
        msg = Twist()
        msg.linear.x = value.linear_x
        msg.linear.y = value.linear_y
        msg.angular.z = value.angular_z
        return msg

    def destroy_node(self):
        self._publish_zero_burst()
        return super().destroy_node()


def main(args=None) -> None:
    rclpy.init(args=args)
    node = SafetySupervisor()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
