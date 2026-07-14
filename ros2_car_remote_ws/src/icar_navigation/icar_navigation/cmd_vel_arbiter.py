"""ROS node that is the sole normal publisher at the `/cmd_vel` boundary."""

import json
import time

from action_msgs.msg import GoalStatusArray
from action_msgs.srv import CancelGoal
from geometry_msgs.msg import Twist
import rclpy
from rclpy.node import Node
from std_msgs.msg import Bool, String
from std_srvs.srv import Trigger

from .alarm_utils import ERROR, WARNING
from .motion_policy import (
    BLOCKED,
    MANUAL,
    NAVIGATION,
    NONE,
    RETURN_HOME,
    ArbitrationDecision,
    MotionPolicy,
    TwistCommand,
)
from .ros_alarm import RosAlarmPublisher


class CmdVelArbiter(Node):
    """Prioritize, limit and fail-close all manual and Nav2 velocity requests."""

    def __init__(self):
        super().__init__('cmd_vel_arbiter')
        defaults = {
            'manual_timeout_sec': 0.30,
            'nav_timeout_sec': 0.30,
            'safety_state_timeout_sec': 0.30,
            'chassis_state_timeout_sec': 0.30,
            'patrol_status_timeout_sec': 0.30,
            'max_linear_x': 0.50,
            'max_linear_y': 0.50,
            'max_angular_z': 2.00,
            'zero_cycles_on_switch': 1,
            'output_rate_hz': 20.0,
        }
        for name, value in defaults.items():
            self.declare_parameter(name, value)

        self.policy = MotionPolicy(
            manual_timeout_sec=self.get_parameter(
                'manual_timeout_sec').value,
            nav_timeout_sec=self.get_parameter('nav_timeout_sec').value,
            safety_state_timeout_sec=self.get_parameter(
                'safety_state_timeout_sec').value,
            chassis_state_timeout_sec=self.get_parameter(
                'chassis_state_timeout_sec').value,
            patrol_status_timeout_sec=self.get_parameter(
                'patrol_status_timeout_sec').value,
            max_linear_x=self.get_parameter('max_linear_x').value,
            max_linear_y=self.get_parameter('max_linear_y').value,
            max_angular_z=self.get_parameter('max_angular_z').value,
            zero_cycles_on_switch=self.get_parameter(
                'zero_cycles_on_switch').value,
        )
        self.alarms = RosAlarmPublisher(self)
        self.command_publisher = self.create_publisher(Twist, '/cmd_vel', 1)
        self.source_publisher = self.create_publisher(
            String, '/control/active_source', 10)
        self.cancel_client = self.create_client(Trigger, '/patrol/cancel')
        self.nav_cancel_client = self.create_client(
            CancelGoal, '/navigate_to_pose/_action/cancel_goal')

        self.create_subscription(
            Twist, '/cmd_vel_manual', self._manual_callback, 1)
        self.create_subscription(
            Twist, '/cmd_vel_nav', self._navigation_callback, 1)
        self.create_subscription(
            String, '/safety/state', self._safety_callback, 10)
        self.create_subscription(
            Bool, '/chassis/connected', self._chassis_callback, 10)
        self.create_subscription(
            String, '/patrol/status', self._patrol_callback, 10)
        self.create_subscription(
            GoalStatusArray, '/navigate_to_pose/_action/status',
            self._navigation_status_callback, 10)

        rate = max(10.0, float(self.get_parameter('output_rate_hz').value))
        self.create_timer(1.0 / rate, self._tick)
        self._last_source = None
        self._last_source_publish_at = -1.0
        self._previous_motion_source = None
        self._cancel_pending = False
        self._cancel_required = False
        self._next_cancel_attempt_at = -1.0
        self._cancel_started_at = None
        self._cancel_token = 0
        self._patrol_cancel_confirmed = False
        self._nav_cancel_pending = False
        self._nav_cancel_started_at = None
        self._nav_cancel_token = 0
        self._nav_cancel_confirmed = False
        self._next_nav_cancel_attempt_at = -1.0
        self._patrol_state = 'UNKNOWN'
        self._patrol_received_at = None
        self._active_nav_goal_count = None
        self._nav_status_received_at = None

    def _manual_callback(self, message):
        accepted = self.policy.update_manual(_from_twist(message), time.monotonic())
        if accepted:
            self.alarms.publish(
                ERROR, 'INVALID_CMD', self._state_name(),
                'manual command stream is finite', active=False)
        else:
            self.alarms.publish(
                ERROR, 'INVALID_CMD', self._state_name(),
                'manual command contained NaN or infinity')

    def _navigation_callback(self, message):
        accepted = self.policy.update_navigation(
            _from_twist(message), time.monotonic())
        if accepted:
            self.alarms.publish(
                ERROR, 'INVALID_NAV_CMD', self._state_name(),
                'navigation command stream is finite', active=False)
        else:
            self.alarms.publish(
                ERROR, 'INVALID_NAV_CMD', self._state_name(),
                'navigation command contained NaN or infinity')

    def _safety_callback(self, message):
        self.policy.update_safety_state(message.data, time.monotonic())

    def _chassis_callback(self, message):
        self.policy.update_chassis_state(message.data, time.monotonic())

    def _patrol_callback(self, message):
        try:
            status = json.loads(message.data)
        except (TypeError, ValueError, json.JSONDecodeError):
            status = None
        received_at = time.monotonic()
        self._patrol_state = (
            str(status.get('state', 'UNKNOWN'))
            if isinstance(status, dict) else 'INVALID')
        self._patrol_received_at = received_at
        self.policy.update_patrol_status(status, received_at)

    def _navigation_status_callback(self, message):
        active_statuses = {1, 2, 3}
        self._active_nav_goal_count = sum(
            1 for item in message.status_list
            if int(item.status) in active_statuses)
        self._nav_status_received_at = time.monotonic()

    def _tick(self):
        now = time.monotonic()
        self._maybe_finish_cancel(now)
        decision = self.policy.decide(now)
        if (self._cancel_required
                and decision.active_source in {NAVIGATION, RETURN_HOME}):
            decision = ArbitrationDecision(
                TwistCommand.zero(), BLOCKED, False,
                'navigation-cancel-pending')
        self.command_publisher.publish(_to_twist(decision.command))
        self._publish_source(decision.active_source, now)

        if (decision.cancel_navigation
                and decision.reason != 'return-home-not-authorized'):
            if not self._cancel_required:
                self._patrol_cancel_confirmed = False
                self._nav_cancel_confirmed = False
            self._cancel_required = True
        if (self._cancel_pending and self._cancel_started_at is not None
                and now - self._cancel_started_at >= 1.0):
            self._cancel_pending = False
            self._cancel_started_at = None
            self._cancel_token += 1
            self._next_cancel_attempt_at = now
            self.alarms.publish(
                WARNING, 'PATROL_CANCEL_FAILED', self._state_name(),
                'patrol cancel service did not answer within 1 second')
        if (self._cancel_required and not self._cancel_pending
                and not self._patrol_cancel_confirmed
                and now >= self._next_cancel_attempt_at):
            self._request_patrol_cancel(now)
        if (self._nav_cancel_pending
                and self._nav_cancel_started_at is not None
                and now - self._nav_cancel_started_at >= 1.0):
            self._nav_cancel_pending = False
            self._nav_cancel_started_at = None
            self._nav_cancel_token += 1
            self._next_nav_cancel_attempt_at = now
            self.alarms.publish(
                WARNING, 'NAV_ACTION_CANCEL_FAILED', self._state_name(),
                'NavigateToPose cancel-all did not answer within 1 second')
        if (self._cancel_required and not self._nav_cancel_pending
                and not self._nav_cancel_confirmed
                and now >= self._next_nav_cancel_attempt_at):
            self._request_navigation_cancel(now)

        if decision.reason == 'safety-state-stale':
            self.alarms.publish(
                ERROR, 'SAFETY_STATE_STALE', BLOCKED,
                'safety heartbeat exceeded 0.30 seconds')
        else:
            self.alarms.publish(
                ERROR, 'SAFETY_STATE_STALE', decision.active_source,
                'safety heartbeat is fresh', active=False)

        if decision.reason in {'chassis-state-stale', 'chassis-disconnected'}:
            self.alarms.publish(
                ERROR, 'CHASSIS_DISCONNECTED', BLOCKED,
                'direct chassis interlock is disconnected or stale')
        else:
            self.alarms.publish(
                ERROR, 'CHASSIS_DISCONNECTED', decision.active_source,
                'direct chassis interlock is connected and fresh',
                active=False)

        motion_sources = {MANUAL, NAVIGATION, RETURN_HOME}
        if (decision.active_source == NONE
                and self._previous_motion_source in motion_sources):
            self.alarms.publish(
                WARNING, 'CMD_TIMEOUT', NONE,
                'active command source exceeded its 0.30 second timeout')
        elif decision.active_source in motion_sources:
            self.alarms.publish(
                WARNING, 'CMD_TIMEOUT', decision.active_source,
                'command source is fresh', active=False)
            self._previous_motion_source = decision.active_source
        elif decision.active_source == BLOCKED:
            self._previous_motion_source = None

    def _publish_source(self, source, now):
        if source != self._last_source or now - self._last_source_publish_at >= 0.5:
            self.source_publisher.publish(String(data=source))
            self._last_source = source
            self._last_source_publish_at = now

    def _request_patrol_cancel(self, now):
        if not self.cancel_client.service_is_ready():
            self._next_cancel_attempt_at = now + 0.5
            self.alarms.publish(
                WARNING, 'PATROL_CANCEL_UNAVAILABLE',
                _zero_or_blocked(self._last_source),
                'manual takeover stopped output but patrol cancel service is unavailable')
            return
        self._cancel_pending = True
        self._cancel_started_at = now
        self._cancel_token += 1
        token = self._cancel_token
        future = self.cancel_client.call_async(Trigger.Request())
        future.add_done_callback(
            lambda completed: self._cancel_complete(completed, token))

    def _cancel_complete(self, future, token):
        if token != self._cancel_token:
            return
        self._cancel_pending = False
        self._cancel_started_at = None
        try:
            response = future.result()
            if not response.success:
                raise RuntimeError(response.message)
            self._patrol_cancel_confirmed = True
            self.alarms.publish(
                WARNING, 'PATROL_CANCEL_FAILED', self._state_name(),
                'manual takeover canceled autonomous patrol', active=False)
            self.alarms.publish(
                WARNING, 'PATROL_CANCEL_UNAVAILABLE', self._state_name(),
                'patrol cancel service is available', active=False)
            self._maybe_finish_cancel()
        except Exception as exc:
            self._next_cancel_attempt_at = time.monotonic() + 0.5
            self.alarms.publish(
                WARNING, 'PATROL_CANCEL_FAILED', self._state_name(),
                'manual takeover could not cancel patrol: {}'.format(exc))

    def _request_navigation_cancel(self, now):
        if not self.nav_cancel_client.service_is_ready():
            self._next_nav_cancel_attempt_at = now + 0.5
            self.alarms.publish(
                WARNING, 'NAV_ACTION_CANCEL_UNAVAILABLE', self._state_name(),
                'NavigateToPose cancel service is unavailable')
            return
        self._nav_cancel_pending = True
        self._nav_cancel_started_at = now
        self._nav_cancel_token += 1
        token = self._nav_cancel_token
        future = self.nav_cancel_client.call_async(CancelGoal.Request())
        future.add_done_callback(
            lambda completed: self._navigation_cancel_complete(
                completed, token))

    def _navigation_cancel_complete(self, future, token):
        if token != self._nav_cancel_token:
            return
        self._nav_cancel_pending = False
        self._nav_cancel_started_at = None
        try:
            response = future.result()
            # action_msgs/CancelGoal return code 1 is ERROR_REJECTED. Codes
            # 2/3 mean the addressed goal is absent/already terminal, which is
            # also a safe result for an all-zero cancel-all request.
            if int(response.return_code) == 1:
                raise RuntimeError(
                    'cancel return code {}'.format(response.return_code))
            self._nav_cancel_confirmed = True
            self.alarms.publish(
                WARNING, 'NAV_ACTION_CANCEL_FAILED', self._state_name(),
                'NavigateToPose cancel-all accepted', active=False)
            self.alarms.publish(
                WARNING, 'NAV_ACTION_CANCEL_UNAVAILABLE', self._state_name(),
                'NavigateToPose cancel service is available', active=False)
            self._maybe_finish_cancel()
        except Exception as exc:
            self._next_nav_cancel_attempt_at = time.monotonic() + 0.5
            self.alarms.publish(
                WARNING, 'NAV_ACTION_CANCEL_FAILED', self._state_name(),
                'NavigateToPose cancel-all failed: {}'.format(exc))

    def _maybe_finish_cancel(self, now=None):
        now = time.monotonic() if now is None else float(now)
        nav_status_fresh = (
            self._nav_status_received_at is not None
            and 0.0 <= now - self._nav_status_received_at <= 1.0)
        patrol_status_fresh = (
            self._patrol_received_at is not None
            and 0.0 <= now - self._patrol_received_at <= 0.30)
        if (self._patrol_cancel_confirmed and self._nav_cancel_confirmed
                and self._patrol_state == 'IDLE'
                and patrol_status_fresh
                and nav_status_fresh
                and self._active_nav_goal_count == 0):
            self._cancel_required = False

    def _state_name(self):
        return self._last_source or NONE


def _zero_or_blocked(source):
    """Return a non-empty state label for an early cancellation alarm."""
    return source or BLOCKED


def _from_twist(message):
    return TwistCommand(
        linear_x=message.linear.x,
        linear_y=message.linear.y,
        angular_z=message.angular.z,
    )


def _to_twist(command):
    message = Twist()
    message.linear.x = command.linear_x
    message.linear.y = command.linear_y
    message.angular.z = command.angular_z
    return message


def main(args=None):
    """Run the command arbiter."""
    rclpy.init(args=args)
    node = CmdVelArbiter()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.command_publisher.publish(Twist())
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
