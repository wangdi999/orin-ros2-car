"""Sequential Foxy NavigateToPose patrol and return-home coordinator."""

import json
import math
import os
import time

from ament_index_python.packages import get_package_share_directory
from geometry_msgs.msg import PoseStamped
from nav2_msgs.action import NavigateToPose
from nav_msgs.msg import Path
import rclpy
from car_interfaces.srv import NavigatePose
from rclpy.action import ActionClient
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import Bool, String
from std_srvs.srv import Trigger

from .alarm_utils import CRITICAL, ERROR, WARNING
from .patrol_policy import (
    ARRIVED,
    CANCELLING,
    IDLE,
    NAVIGATING,
    NEXT_GOAL,
    RETURN_HOME,
    SINGLE_GOAL,
    WAITING,
    PatrolPolicy,
)
from .ros_alarm import RosAlarmPublisher
from .route_loader import (
    RouteValidationError,
    Waypoint,
    load_route,
    require_executable_route,
    route_path_points,
)
from .safety_policy import LOW_BATTERY_RETURN, READY


class PatrolManager(Node):
    """Own one navigation goal at a time and expose deterministic services."""

    def __init__(self):
        super().__init__('patrol_manager')
        default_route = os.path.join(
            get_package_share_directory('icar_navigation'),
            'config', 'patrol_route.yaml')
        defaults = {
            'route_file': default_route,
            'goal_timeout_sec': 120.0,
            'safety_state_timeout_sec': 0.30,
            'status_active_rate_hz': 10.0,
            'status_idle_rate_hz': 2.0,
        }
        for name, value in defaults.items():
            self.declare_parameter(name, value)

        self.goal_timeout_sec = max(
            1.0, float(self.get_parameter('goal_timeout_sec').value))
        self.safety_timeout_sec = float(
            self.get_parameter('safety_state_timeout_sec').value)
        active_rate = max(
            2.0, float(self.get_parameter('status_active_rate_hz').value))
        self.active_publish_period = 1.0 / active_rate
        idle_rate = max(
            0.5, float(self.get_parameter('status_idle_rate_hz').value))
        self.idle_publish_period = 1.0 / idle_rate

        self.policy = PatrolPolicy()
        self.route = None
        self.route_error = ''
        try:
            self.route = load_route(self.get_parameter('route_file').value)
            self.policy.route = self.route
        except RouteValidationError as exc:
            self.route_error = str(exc)

        self.alarms = RosAlarmPublisher(self)
        self.status_publisher = self.create_publisher(
            String, '/patrol/status', 10)
        self.navigation_status_publisher = self.create_publisher(
            String, '/navigation/status', 10)
        route_qos = QoSProfile(depth=1)
        route_qos.durability = DurabilityPolicy.TRANSIENT_LOCAL
        route_qos.reliability = ReliabilityPolicy.RELIABLE
        self.route_publisher = self.create_publisher(Path, '/patrol/route', route_qos)
        self.estop_publisher = self.create_publisher(
            Bool, '/safety/estop', 10)
        self.action_client = ActionClient(
            self, NavigateToPose, '/navigate_to_pose')
        self.create_subscription(
            String, '/safety/state', self._safety_callback, 10)
        self.create_service(Trigger, '/patrol/start', self._start_callback)
        self.create_service(Trigger, '/patrol/cancel', self._cancel_callback)
        self.create_service(
            Trigger, '/patrol/return_home', self._return_home_callback)
        self.create_service(
            Trigger, '/patrol/reload_route', self._reload_route_callback)
        self.create_service(
            NavigatePose, '/navigation/send_goal', self._single_goal_callback)
        self.create_service(
            Trigger, '/navigation/cancel', self._cancel_callback)

        self._safety_state = None
        self._safety_received_at = None
        self._goal_handle = None
        self._goal_request_future = None
        self._goal_started_at = None
        self._goal_token = 0
        self._dwell_deadline = None
        self._pending_return_home = False
        self._cancel_deadline = None
        self._remote_cancel_pending = False
        self._cancel_for_timeout = False
        self._low_battery_handled = False
        self._last_status_publish_at = -math.inf
        self._web_goal_sequence = 0

        self.create_timer(0.05, self._tick)
        self._publish_route()
        self._publish_route_alarm()
        self._publish_status(force=True)

    def _safety_callback(self, message):
        previous = self._safety_state
        self._safety_state = message.data
        self._safety_received_at = time.monotonic()
        if self._safety_state == LOW_BATTERY_RETURN:
            if not self._low_battery_handled:
                self._low_battery_handled = True
                self._request_return_home('low_battery')
        else:
            self._low_battery_handled = False
            if (self._safety_state != READY and self.policy.active
                    and previous != self._safety_state):
                self._cancel_active('safety_{}'.format(self._safety_state.lower()))

    def _start_callback(self, _request, response):
        ok, reason = self._service_preconditions(require_idle=True)
        if not ok:
            response.success = False
            response.message = reason
            return response
        transition = self.policy.start_patrol(self.route)
        self._handle_transition(transition)
        response.success = True
        response.message = 'patrol accepted'
        return response

    def _cancel_callback(self, _request, response):
        if not self.policy.active and self._goal_handle is None:
            response.success = True
            response.message = 'patrol is already idle'
            return response
        self._cancel_active('operator_cancel')
        response.success = True
        response.message = 'patrol cancellation requested'
        return response

    def _return_home_callback(self, _request, response):
        ok, reason = self._service_preconditions(require_idle=False)
        if not ok:
            response.success = False
            response.message = reason
            return response
        self._request_return_home('operator_return_home')
        response.success = True
        response.message = 'return-home accepted'
        return response

    def _single_goal_callback(self, request, response):
        ok, reason = self._single_goal_preconditions()
        if not ok:
            response.accepted = False
            response.goal_id = ''
            response.message = reason
            return response
        values = (request.x, request.y, request.yaw)
        if not all(math.isfinite(value) for value in values):
            response.accepted = False
            response.goal_id = ''
            response.message = 'goal coordinates must be finite'
            return response
        if not -math.pi <= request.yaw <= math.pi:
            response.accepted = False
            response.goal_id = ''
            response.message = 'goal yaw must be within [-pi, pi]'
            return response
        self._web_goal_sequence += 1
        goal_id = 'web-{}-{}'.format(
            int(self.get_clock().now().nanoseconds), self._web_goal_sequence)
        transition = self.policy.start_single_goal(
            Waypoint('web_goal', request.x, request.y, request.yaw), goal_id)
        self._handle_transition(transition)
        response.accepted = bool(transition.send_goal)
        response.goal_id = goal_id if response.accepted else ''
        response.message = ('single goal accepted' if response.accepted
                            else transition.event)
        return response

    def _reload_route_callback(self, _request, response):
        if self.policy.active or self._goal_handle is not None:
            response.success = False
            response.message = 'route cannot be reloaded while navigation is active'
            return response
        try:
            route = load_route(self.get_parameter('route_file').value)
        except RouteValidationError as exc:
            self.route_error = str(exc)
            response.success = False
            response.message = self.route_error
            self._publish_route_alarm()
            return response
        self.route = route
        self.route_error = ''
        self.policy.route = route
        self._publish_route()
        self._publish_route_alarm()
        self._publish_status(force=True)
        response.success = True
        response.message = 'route reloaded'
        return response

    def _single_goal_preconditions(self):
        now = time.monotonic()
        if not self._safety_fresh(now) or self._safety_state != READY:
            return False, 'safety state is not fresh READY'
        if self.policy.active or self._goal_handle is not None:
            return False, 'another navigation goal is active'
        if not self.action_client.server_is_ready():
            return False, 'NavigateToPose action server is unavailable'
        return True, 'preconditions pass'

    def _service_preconditions(self, require_idle):
        now = time.monotonic()
        if not self._safety_fresh(now) or self._safety_state != READY:
            return False, 'safety state is not fresh READY'
        try:
            require_executable_route(self.route)
        except RouteValidationError as exc:
            return False, str(exc)
        if require_idle and (self.policy.active or self._goal_handle is not None):
            return False, 'another patrol or navigation goal is active'
        if not self.action_client.server_is_ready():
            return False, 'NavigateToPose action server is unavailable'
        return True, 'preconditions pass'

    def _request_return_home(self, reason):
        try:
            require_executable_route(self.route)
        except RouteValidationError as exc:
            self.policy.fail_return_home('route-not-configured')
            self.alarms.publish(
                CRITICAL, 'RETURN_HOME_FAILED', RETURN_HOME,
                'return-home rejected: {}'.format(exc))
            self._publish_status(force=True)
            return
        if not self.action_client.server_is_ready():
            self.policy.fail_return_home('action-server-unavailable')
            self.alarms.publish(
                CRITICAL, 'RETURN_HOME_FAILED', RETURN_HOME,
                'NavigateToPose action server is unavailable')
            self._publish_status(force=True)
            return
        if self.policy.active or self._goal_handle is not None:
            self._pending_return_home = True
            self._cancel_active(reason)
            return
        self._start_return_home()

    def _start_return_home(self):
        self._pending_return_home = False
        transition = self.policy.start_return_home(self.route)
        self._handle_transition(transition)

    def _send_current_goal(self):
        waypoint = self.policy.current_waypoint
        if waypoint is None:
            self._handle_transition(self.policy.fail_return_home('goal-missing'))
            return
        if not self._safety_allows_current_goal():
            self._cancel_active('safety-not-authorized')
            return

        goal = NavigateToPose.Goal()
        goal.pose = PoseStamped()
        goal.pose.header.stamp = self.get_clock().now().to_msg()
        goal.pose.header.frame_id = (
            'map' if self.policy.mode == SINGLE_GOAL else self.route.frame_id)
        goal.pose.pose.position.x = waypoint.x
        goal.pose.pose.position.y = waypoint.y
        goal.pose.pose.orientation.z = math.sin(waypoint.yaw / 2.0)
        goal.pose.pose.orientation.w = math.cos(waypoint.yaw / 2.0)

        self._goal_token += 1
        token = self._goal_token
        self._goal_started_at = time.monotonic()
        future = self.action_client.send_goal_async(goal)
        self._goal_request_future = future
        future.add_done_callback(
            lambda result_future: self._goal_response(result_future, token))
        self._publish_status(force=True)

    def _goal_response(self, future, token):
        if future is self._goal_request_future:
            self._goal_request_future = None
        try:
            goal_handle = future.result()
        except Exception as exc:
            self.get_logger().error('Goal request failed: %s' % exc)
            if token != self._goal_token:
                return
            if self.policy.state == CANCELLING:
                self._cancel_complete()
                return
            self._process_goal_result(0, rejected=True)
            return
        if token != self._goal_token:
            if goal_handle is not None and goal_handle.accepted:
                try:
                    goal_handle.cancel_goal_async()
                except Exception as exc:
                    self.get_logger().error(
                        'Unable to cancel superseded goal: %s' % exc)
            return
        if goal_handle is None or not goal_handle.accepted:
            self._goal_started_at = None
            if self.policy.state == CANCELLING:
                self._cancel_complete()
                return
            self._process_goal_result(0, rejected=True)
            return
        self._goal_handle = goal_handle
        result_future = goal_handle.get_result_async()
        result_future.add_done_callback(
            lambda completed: self._goal_result(completed, token))
        if self.policy.state == CANCELLING:
            self._issue_goal_cancel(goal_handle)
            return

    def _goal_result(self, future, token):
        if token != self._goal_token:
            return
        self._goal_handle = None
        self._goal_started_at = None
        try:
            wrapped_result = future.result()
            status = wrapped_result.status
            # Foxy result.result is std_msgs/Empty and is intentionally ignored.
        except Exception as exc:
            self.get_logger().error('Goal result failed: %s' % exc)
            status = 0
        if self.policy.state == CANCELLING:
            self._remote_cancel_pending = False
            self._cancel_complete(terminal_status=status)
            return
        self._process_goal_result(status)

    def _process_goal_result(self, status, *, rejected=False, timed_out=False):
        transition = self.policy.handle_goal_result(
            status, rejected=rejected, timed_out=timed_out)
        self._handle_transition(transition)

    def _handle_transition(self, transition):
        event = transition.event
        if transition.publish_alarm:
            self._publish_transition_alarm(event)
        elif event in {'goal-arrived', 'home-reached'}:
            self.alarms.publish(
                ERROR, 'NAV_GOAL_FAILED', self.policy.state,
                'NavigateToPose recovered', active=False)
        self._publish_status(force=True)

        if event == 'waypoint-skipped':
            self._handle_transition(self.policy.advance_after_next_goal())
            return
        if transition.send_goal:
            self._send_current_goal()

    def _cancel_active(self, reason, *, timeout_retry=False):
        if self.policy.state != CANCELLING:
            self.policy.cancel(reason)
        if timeout_retry and not self._pending_return_home:
            self._cancel_for_timeout = True
        elif not timeout_retry:
            self._cancel_for_timeout = False
        self._goal_started_at = None
        self._dwell_deadline = None
        if self._cancel_deadline is None:
            self._cancel_deadline = time.monotonic() + 2.0
        self._publish_status(force=True)
        if self._remote_cancel_pending or self._goal_request_future is not None:
            return
        if self._goal_handle is None:
            self._cancel_complete()
            return
        self._issue_goal_cancel(self._goal_handle)

    def _issue_goal_cancel(self, handle):
        if self._remote_cancel_pending:
            return
        self._remote_cancel_pending = True
        token = self._goal_token
        try:
            future = handle.cancel_goal_async()
            future.add_done_callback(
                lambda completed: self._cancel_response(completed, token))
        except Exception as exc:
            self.get_logger().error('Goal cancellation failed: %s' % exc)
            self._cancel_timed_out()

    def _cancel_response(self, future, token):
        if token != self._goal_token or self.policy.state != CANCELLING:
            return
        try:
            response = future.result()
            if not getattr(response, 'goals_canceling', []):
                raise RuntimeError('action server rejected cancellation')
        except Exception as exc:
            self.get_logger().error('Goal cancellation rejected: %s' % exc)
            self._cancel_timed_out()

    def _cancel_complete(self, terminal_status=None):
        self._cancel_deadline = None
        self._remote_cancel_pending = False
        self._goal_handle = None
        self._goal_started_at = None
        self._goal_token += 1
        if self._pending_return_home:
            self.policy.cancellation_complete()
            self._start_return_home()
            return
        if self.policy.state == CANCELLING and self._cancel_for_timeout:
            self._cancel_for_timeout = False
            transition = self.policy.timeout_cancellation_complete(
                terminal_status=terminal_status)
            self._handle_transition(transition)
            return
        if self.policy.state == CANCELLING:
            self.policy.cancellation_complete()
        self._publish_status(force=True)

    def _tick(self):
        now = time.monotonic()
        if (self.policy.state == CANCELLING
                and self._cancel_deadline is not None
                and now >= self._cancel_deadline):
            self._cancel_timed_out()
            return
        if self.policy.active and not self._safety_fresh(now):
            self._cancel_active('safety-state-stale')
            return
        if (self.policy.state == NAVIGATING
                and self._goal_started_at is not None
                and now - self._goal_started_at >= self.goal_timeout_sec):
            self._cancel_active('goal_timeout', timeout_retry=True)
            return
        if self.policy.state == ARRIVED:
            waypoint = self.policy.current_waypoint
            dwell = waypoint.dwell_sec
            if dwell is None:
                dwell = self.route.default_dwell_sec
            self.policy.begin_waiting()
            self._dwell_deadline = now + dwell
            self._publish_status(force=True)
        elif (self.policy.state == WAITING and self._dwell_deadline is not None
              and now >= self._dwell_deadline):
            self._dwell_deadline = None
            self._handle_transition(self.policy.dwell_elapsed())
        self._publish_status()

    def _cancel_timed_out(self):
        self._cancel_deadline = None
        self._remote_cancel_pending = False
        self._goal_request_future = None
        self._goal_handle = None
        self._goal_started_at = None
        self._goal_token += 1
        self.estop_publisher.publish(Bool(data=True))
        self.alarms.publish(
            CRITICAL, 'NAV_CANCEL_FAILED', CANCELLING,
            'NavigateToPose did not confirm cancellation within 2 seconds')
        if self._pending_return_home or self.policy.mode == RETURN_HOME:
            self._pending_return_home = False
            self.policy.fail_return_home('cancel-timeout')
        else:
            self.policy.cancellation_complete()
        self._cancel_for_timeout = False
        self._publish_status(force=True)

    def _safety_fresh(self, now):
        if self._safety_received_at is None:
            return False
        age = now - self._safety_received_at
        return 0.0 <= age <= self.safety_timeout_sec

    def _safety_allows_current_goal(self):
        now = time.monotonic()
        if not self._safety_fresh(now):
            return False
        if self.policy.mode == RETURN_HOME:
            return self._safety_state in {READY, LOW_BATTERY_RETURN}
        return self._safety_state == READY

    def _publish_status(self, force=False):
        now = time.monotonic()
        period = (self.active_publish_period if self.policy.active
                  else self.idle_publish_period)
        if not force and now - self._last_status_publish_at < period:
            return
        payload = self.policy.status_dict()
        if self.route is not None:
            payload['route_configured'] = bool(self.route.configured)
        else:
            payload['route_configured'] = False
        serialized = json.dumps(payload, sort_keys=True, separators=(',', ':'))
        self.status_publisher.publish(String(data=serialized))
        self.navigation_status_publisher.publish(String(data=serialized))
        self._last_status_publish_at = now

    def _publish_route(self):
        """Publish the configured map route without creating a navigation goal."""
        message = Path()
        message.header.stamp = self.get_clock().now().to_msg()
        message.header.frame_id = 'map'
        for x, y, yaw in route_path_points(self.route):
            pose = PoseStamped()
            pose.header = message.header
            pose.pose.position.x = x
            pose.pose.position.y = y
            pose.pose.orientation.z = math.sin(yaw / 2.0)
            pose.pose.orientation.w = math.cos(yaw / 2.0)
            message.poses.append(pose)
        self.route_publisher.publish(message)

    def _publish_route_alarm(self):
        if self.route_error:
            self.alarms.publish(
                CRITICAL, 'ROUTE_INVALID', IDLE,
                'route cannot be parsed: {}'.format(self.route_error))
        elif self.route is not None and not self.route.configured:
            self.alarms.publish(
                WARNING, 'ROUTE_NOT_CONFIGURED', IDLE,
                'route coordinates are null; patrol and return-home are disabled')
        else:
            self.alarms.publish(
                WARNING, 'ROUTE_NOT_CONFIGURED', IDLE,
                'route is configured', active=False)

    def _publish_transition_alarm(self, event):
        if event == 'waypoint-skipped':
            self.alarms.publish(
                WARNING, 'WAYPOINT_SKIPPED', NEXT_GOAL,
                'waypoint failed after one retry and was skipped')
        elif event == 'return-failed':
            self.alarms.publish(
                CRITICAL, 'RETURN_HOME_FAILED', RETURN_HOME,
                'Home failed after one retry', active=True)
        else:
            self.alarms.publish(
                ERROR, 'NAV_GOAL_FAILED', self.policy.state,
                'NavigateToPose event: {}'.format(event))


def main(args=None):
    """Run the patrol manager."""
    rclpy.init(args=args)
    node = PatrolManager()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
