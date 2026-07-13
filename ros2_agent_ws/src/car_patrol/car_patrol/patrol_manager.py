from __future__ import annotations

import json
import math
from pathlib import Path
from uuid import uuid4

import rclpy
from action_msgs.msg import GoalStatus
from ament_index_python.packages import get_package_share_directory
from car_interfaces.msg import PatrolEvent, PatrolStatus
from car_interfaces.srv import ControlPatrol, CreatePatrol
from geometry_msgs.msg import PoseStamped
from nav2_msgs.action import NavigateToPose
from rclpy.action import ActionClient
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node

from .location_store import LocationStore, NamedLocation
from .task_state import PatrolState, PatrolTask


ACTIVE_STATES = {
    PatrolState.READY,
    PatrolState.RUNNING,
    PatrolState.PAUSED,
    PatrolState.RECOVERY_REQUIRED,
}


class PatrolManager(Node):
    def __init__(self) -> None:
        super().__init__("patrol_manager")
        self._callbacks = ReentrantCallbackGroup()
        self.declare_parameter("locations_file", "")
        self.declare_parameter("max_retries", 1)
        self.declare_parameter("nav_action_name", "navigate_to_pose")
        self.declare_parameter("map_frame", "map")
        self.declare_parameter("retry_delay_sec", 1.0)

        locations_file = str(self.get_parameter("locations_file").value)
        if not locations_file:
            locations_file = str(
                Path(get_package_share_directory("car_patrol")) / "config" / "locations.yaml"
            )
        self._locations = LocationStore(locations_file)
        self._max_retries = int(self.get_parameter("max_retries").value)
        self._map_frame = str(self.get_parameter("map_frame").value)
        self._retry_delay_sec = float(self.get_parameter("retry_delay_sec").value)

        action_name = str(self.get_parameter("nav_action_name").value)
        self._nav = ActionClient(
            self,
            NavigateToPose,
            action_name,
            callback_group=self._callbacks,
        )
        self._status_pub = self.create_publisher(PatrolStatus, "/patrol/status", 10)
        self._event_pub = self.create_publisher(PatrolEvent, "/patrol/events", 50)
        self.create_service(
            CreatePatrol,
            "/patrol/create",
            self._on_create,
            callback_group=self._callbacks,
        )
        self.create_service(
            ControlPatrol,
            "/patrol/control",
            self._on_control,
            callback_group=self._callbacks,
        )
        self.create_timer(0.5, self._publish_status, callback_group=self._callbacks)

        self._task: PatrolTask | None = None
        self._resolved: dict[str, NamedLocation] = {}
        self._active_goal_handle = None
        self._goal_token = 0
        self._nav_status = "IDLE"
        self.get_logger().info(f"Patrol Manager ready; locations={locations_file}")

    def _on_create(self, request: CreatePatrol.Request, response: CreatePatrol.Response):
        if self._task and self._task.state in ACTIVE_STATES:
            if self._task.task_id == request.task_id:
                response.accepted = True
                return response
            return self._reject_create(response, "TASK_ALREADY_RUNNING", self._task.task_id)
        if not request.task_id:
            return self._reject_create(response, "TASK_ID_REQUIRED", "task_id is empty")
        if not 1 <= len(request.location_ids) <= 10:
            return self._reject_create(response, "INVALID_WAYPOINT_COUNT", "expected 1..10")

        location_ids = list(request.location_ids)
        if request.return_home and (not location_ids or location_ids[-1] != "home"):
            location_ids.append("home")
        resolved, errors = self._locations.resolve_enabled(location_ids)
        if errors:
            return self._reject_create(response, "LOCATION_VALIDATION_FAILED", ",".join(errors))

        try:
            event_policy = json.loads(request.event_policy_json or "{}")
        except json.JSONDecodeError as exc:
            return self._reject_create(response, "INVALID_EVENT_POLICY_JSON", str(exc))

        self._task = PatrolTask(
            task_id=request.task_id,
            name=request.name or request.task_id,
            location_ids=location_ids,
            event_policy=event_policy,
            return_home=request.return_home,
            max_retries=self._max_retries,
        )
        self._resolved = {item.location_id: item for item in resolved}
        self._nav_status = "READY"
        self._emit("TASK_CREATED", "INFO", {"name": self._task.name, "locations": location_ids})
        self._publish_status()
        response.accepted = True
        return response

    def _reject_create(self, response, code: str, message: str):
        response.accepted = False
        response.error_code = code
        response.error_message = message
        return response

    def _on_control(self, request: ControlPatrol.Request, response: ControlPatrol.Response):
        task = self._task
        if task is None or task.task_id != request.task_id:
            return self._reject_control(response, "TASK_NOT_FOUND", request.task_id)
        operation = request.operation.upper()
        try:
            if operation == "START":
                task.start()
                self._emit("TASK_STARTED", "INFO", {"reason": request.reason})
                self._send_current_goal()
            elif operation == "PAUSE":
                task.pause()
                self._goal_token += 1
                self._cancel_active_goal()
                self._nav_status = "PAUSED"
                self._emit("TASK_PAUSED", "WARN", {"reason": request.reason})
            elif operation == "RESUME":
                task.resume()
                self._emit("TASK_RESUMED", "INFO", {"reason": request.reason})
                self._send_current_goal()
            elif operation == "CANCEL":
                task.cancel()
                self._goal_token += 1
                self._cancel_active_goal()
                self._nav_status = "CANCELLED"
                self._emit("TASK_CANCELLED", "WARN", {"reason": request.reason})
            elif operation == "RETRY_CURRENT":
                task.retry_current()
                self._emit("WAYPOINT_RETRY_REQUESTED", "WARN", {"reason": request.reason})
                self._send_current_goal()
            elif operation == "SKIP_CURRENT":
                skipped = task.current_location_id
                task.skip_current()
                self._emit("WAYPOINT_SKIPPED", "WARN", {"location_id": skipped})
                if task.state == PatrolState.SUCCEEDED:
                    self._finish_success()
                else:
                    self._send_current_goal()
            else:
                return self._reject_control(response, "INVALID_OPERATION", operation)
        except ValueError as exc:
            return self._reject_control(response, "INVALID_STATE_TRANSITION", str(exc))

        self._publish_status()
        response.success = True
        response.state = task.state.value
        return response

    def _reject_control(self, response, code: str, message: str):
        response.success = False
        response.state = self._task.state.value if self._task else PatrolState.IDLE.value
        response.error_code = code
        response.error_message = message
        return response

    def _send_current_goal(self) -> None:
        task = self._task
        if task is None or task.state != PatrolState.RUNNING:
            return
        if task.complete:
            self._finish_success()
            return
        if not self._nav.wait_for_server(timeout_sec=0.2):
            task.state = PatrolState.RECOVERY_REQUIRED
            task.last_error_code = "NAV2_NOT_READY"
            task.last_error_message = "NavigateToPose action server unavailable"
            self._nav_status = "NAV2_NOT_READY"
            self._emit("WAYPOINT_FAILED", "ERROR", {"error_code": "NAV2_NOT_READY"})
            self._publish_status()
            return

        location_id = task.current_location_id
        location = self._resolved[location_id]
        goal = NavigateToPose.Goal()
        goal.pose = self._pose(location)
        self._goal_token += 1
        token = self._goal_token
        self._nav_status = "GOAL_SENDING"
        self._emit(
            "WAYPOINT_STARTED",
            "INFO",
            {"index": task.current_index, "location_id": location_id},
        )
        future = self._nav.send_goal_async(goal, feedback_callback=self._on_feedback)
        future.add_done_callback(lambda item, goal_token=token: self._on_goal_response(item, goal_token))

    def _pose(self, location: NamedLocation) -> PoseStamped:
        pose = PoseStamped()
        pose.header.frame_id = self._map_frame
        pose.header.stamp = self.get_clock().now().to_msg()
        pose.pose.position.x = location.x
        pose.pose.position.y = location.y
        pose.pose.orientation.z = math.sin(location.yaw / 2.0)
        pose.pose.orientation.w = math.cos(location.yaw / 2.0)
        return pose

    def _on_goal_response(self, future, token: int) -> None:
        if token != self._goal_token or self._task is None:
            return
        goal_handle = future.result()
        if not goal_handle.accepted:
            self._handle_navigation_failure("GOAL_REJECTED", "Nav2 rejected goal")
            return
        self._active_goal_handle = goal_handle
        self._nav_status = "NAVIGATING"
        result_future = goal_handle.get_result_async()
        result_future.add_done_callback(
            lambda item, goal_token=token: self._on_goal_result(item, goal_token)
        )

    def _on_goal_result(self, future, token: int) -> None:
        if token != self._goal_token or self._task is None:
            return
        wrapped = future.result()
        self._active_goal_handle = None
        if self._task.state in {PatrolState.PAUSED, PatrolState.CANCELLED}:
            return
        if wrapped.status == GoalStatus.STATUS_SUCCEEDED:
            completed = self._task.current_location_id
            self._task.waypoint_succeeded()
            self._nav_status = "SUCCEEDED"
            self._emit(
                "WAYPOINT_SUCCEEDED",
                "INFO",
                {"location_id": completed, "next_index": self._task.current_index},
            )
            if self._task.state == PatrolState.SUCCEEDED:
                self._finish_success()
            else:
                self._send_current_goal()
            return
        if wrapped.status == GoalStatus.STATUS_CANCELED:
            self._handle_navigation_failure("GOAL_CANCELLED", "Nav2 goal was cancelled")
            return
        self._handle_navigation_failure("NAVIGATION_FAILED", f"goal status={wrapped.status}")

    def _handle_navigation_failure(self, code: str, message: str) -> None:
        task = self._task
        if task is None or task.state != PatrolState.RUNNING:
            return
        retry = task.waypoint_failed(code, message)
        self._nav_status = code
        self._emit(
            "WAYPOINT_FAILED",
            "ERROR",
            {
                "location_id": task.current_location_id,
                "retry_count": task.retry_count,
                "error_code": code,
                "error_message": message,
            },
        )
        self._publish_status()
        if retry:
            self._schedule_once(self._retry_delay_sec, self._send_current_goal)

    def _finish_success(self) -> None:
        if self._task is None:
            return
        self._task.state = PatrolState.SUCCEEDED
        self._nav_status = "SUCCEEDED"
        self._emit("TASK_SUCCEEDED", "INFO", {"waypoints": len(self._task.location_ids)})
        self._publish_status()

    def _cancel_active_goal(self) -> None:
        if self._active_goal_handle is not None:
            self._active_goal_handle.cancel_goal_async()
            self._active_goal_handle = None

    def _schedule_once(self, delay_sec: float, callback) -> None:
        holder = {}

        def run_once():
            timer = holder["timer"]
            timer.cancel()
            callback()

        holder["timer"] = self.create_timer(delay_sec, run_once, callback_group=self._callbacks)

    def _on_feedback(self, feedback) -> None:
        del feedback
        self._nav_status = "NAVIGATING"

    def _publish_status(self) -> None:
        msg = PatrolStatus()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = self._map_frame
        if self._task is None:
            msg.state = PatrolState.IDLE.value
            msg.nav_status = "IDLE"
        else:
            task = self._task
            msg.task_id = task.task_id
            msg.state = task.state.value
            msg.current_index = task.current_index
            msg.total_waypoints = len(task.location_ids)
            msg.current_location_id = task.current_location_id
            location = self._resolved.get(task.current_location_id)
            msg.current_location_name = location.display_name if location else ""
            msg.nav_status = self._nav_status
            msg.last_error_code = task.last_error_code
            msg.last_error_message = task.last_error_message
        self._status_pub.publish(msg)

    def _emit(self, event_type: str, severity: str, payload: dict) -> None:
        msg = PatrolEvent()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = self._map_frame
        msg.event_id = str(uuid4())
        msg.task_id = self._task.task_id if self._task else ""
        msg.event_type = event_type
        msg.severity = severity
        msg.payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        self._event_pub.publish(msg)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = PatrolManager()
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    try:
        executor.spin()
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
