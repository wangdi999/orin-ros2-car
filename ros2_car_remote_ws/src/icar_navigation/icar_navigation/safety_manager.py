"""Authoritative health monitor, safety latch and low-battery coordinator."""

import json
import math
import time

from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
import rclpy
from rclpy.node import Node
from rclpy.time import Time
from sensor_msgs.msg import LaserScan
from std_msgs.msg import Bool, Float32, String
from std_srvs.srv import Trigger
from tf2_ros import Buffer, TransformException, TransformListener

from .alarm_utils import CRITICAL, ERROR, INFO
from .patrol_policy import (
    ARRIVED,
    CANCELLING,
    NAVIGATING,
    NEXT_GOAL,
    WAITING,
)
from .ros_alarm import RosAlarmPublisher
from .safety_policy import (
    CHASSIS_FAULT,
    ESTOP,
    INITIALIZING,
    LOW_BATTERY_RETURN,
    ODOM_TF_FAULT,
    OWNERSHIP_FAULT,
    READY,
    RETURNED_HOME,
    RETURN_FAILED,
    SENSOR_FAULT,
    BatteryMonitor,
    HealthSnapshot,
    SafetyPolicy,
)


class SafetyManager(Node):
    """Fail-closed supervisor for topics, TF, chassis and return-home state."""

    def __init__(self):
        super().__init__('safety_manager')
        defaults = {
            'runtime_mode': 'base',
            'startup_grace_sec': 5.0,
            'chassis_timeout_sec': 0.30,
            'scan_timeout_sec': 0.40,
            'odom_timeout_sec': 0.20,
            'ownership_check_period_sec': 0.20,
            'expected_cmd_vel_publisher': 'cmd_vel_arbiter',
            'expected_odom_publisher': 'ekf_filter_node',
            'expected_scan_publisher': 'sllidar_node',
            'enable_real_low_battery': False,
            'low_battery_window': 10,
            'low_battery_threshold_v': 10.8,
            'low_battery_recovery_v': 11.1,
            'low_battery_sustain_sec': 5.0,
            'alarm_repeat_sec': 5.0,
        }
        for name, value in defaults.items():
            self.declare_parameter(name, value)

        now = time.monotonic()
        self.runtime_mode = str(self.get_parameter('runtime_mode').value)
        if self.runtime_mode not in {'base', 'mapping', 'navigation'}:
            raise ValueError('runtime_mode must be base, mapping or navigation')
        self.policy = SafetyPolicy(
            started_at=now,
            startup_grace_sec=self.get_parameter('startup_grace_sec').value,
            chassis_timeout_sec=self.get_parameter('chassis_timeout_sec').value,
            scan_timeout_sec=self.get_parameter('scan_timeout_sec').value,
            odom_timeout_sec=self.get_parameter('odom_timeout_sec').value,
        )
        self.battery = BatteryMonitor(
            window_size=self.get_parameter('low_battery_window').value,
            threshold_v=self.get_parameter('low_battery_threshold_v').value,
            recovery_v=self.get_parameter('low_battery_recovery_v').value,
            sustain_sec=self.get_parameter('low_battery_sustain_sec').value,
        )
        self.real_low_battery_enabled = bool(
            self.get_parameter('enable_real_low_battery').value)
        self.ownership_period = float(
            self.get_parameter('ownership_check_period_sec').value)
        self.expected_publishers = {
            '/cmd_vel': str(self.get_parameter(
                'expected_cmd_vel_publisher').value),
            '/odom': str(self.get_parameter('expected_odom_publisher').value),
            '/scan': str(self.get_parameter('expected_scan_publisher').value),
        }

        self.alarms = RosAlarmPublisher(
            self, repeat_sec=self.get_parameter('alarm_repeat_sec').value)
        self.state_publisher = self.create_publisher(
            String, '/safety/state', 10)
        self.reset_service = self.create_service(
            Trigger, '/safety/reset', self._reset_callback)
        self.simulate_service = self.create_service(
            Trigger, '/safety/simulate_low_battery',
            self._simulate_low_battery_callback)

        self.create_subscription(
            Bool, '/safety/estop', self._estop_callback, 10)
        self.create_subscription(
            Bool, '/chassis/connected', self._chassis_callback, 10)
        self.create_subscription(LaserScan, '/scan', self._scan_callback, 10)
        self.create_subscription(Odometry, '/odom', self._odom_callback, 20)
        self.create_subscription(Float32, '/voltage', self._voltage_callback, 10)
        self.create_subscription(
            String, '/patrol/status', self._patrol_callback, 10)
        self.create_subscription(Twist, '/cmd_vel', self._command_callback, 10)

        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)

        self._chassis_connected = False
        self._chassis_received_at = None
        self._scan_received_at = None
        self._odom_received_at = None
        self._patrol_received_at = None
        self._patrol_status = None
        self._patrol_expected_active = False
        self._output_is_zero = True
        self._ownership_valid = False
        self._ownership_reason = 'ownership graph not checked'
        self._last_ownership_check_at = -math.inf
        self._last_state_publish_at = -math.inf
        self._last_published_state = None
        self._active_state_alarm = None
        self._latest_health = HealthSnapshot()

        self.create_timer(0.05, self._tick)

    def _estop_callback(self, message):
        self.policy.set_estop(message.data)
        self._publish_state(force=True)

    def _chassis_callback(self, message):
        self._chassis_connected = bool(message.data)
        self._chassis_received_at = time.monotonic()

    def _scan_callback(self, _message):
        self._scan_received_at = time.monotonic()

    def _odom_callback(self, _message):
        self._odom_received_at = time.monotonic()

    def _command_callback(self, message):
        values = (message.linear.x, message.linear.y, message.angular.z)
        self._output_is_zero = all(
            math.isfinite(value) and abs(value) <= 1e-9 for value in values)

    def _voltage_callback(self, message):
        now = time.monotonic()
        triggered = self.battery.add_sample(
            message.data, now, enabled=self.real_low_battery_enabled)
        if triggered and self.policy.state == READY:
            ok, reason = self._return_preconditions(now)
            if ok:
                self.policy.request_low_battery_return(
                    self._latest_health, now)
            else:
                self.policy.force_return_failed(
                    'real low battery cannot return: {}'.format(reason))

    def _patrol_callback(self, message):
        try:
            status = json.loads(message.data)
            if not isinstance(status, dict):
                raise ValueError('status must be an object')
        except (TypeError, ValueError, json.JSONDecodeError):
            self._patrol_status = None
            self._patrol_received_at = time.monotonic()
            return
        self._patrol_status = status
        self._patrol_received_at = time.monotonic()
        if status.get('state') in {
                NAVIGATING, ARRIVED, WAITING, NEXT_GOAL, CANCELLING}:
            self._patrol_expected_active = True
        elif status.get('state') == 'IDLE':
            self._patrol_expected_active = False
        if self.policy.state == LOW_BATTERY_RETURN:
            if status.get('reason') == 'home_reached':
                self.policy.report_return_result(True)
            elif status.get('reason') == 'return_failed':
                self.policy.report_return_result(False)

    def _tick(self):
        now = time.monotonic()
        if now - self._last_ownership_check_at >= self.ownership_period:
            self._ownership_valid, self._ownership_reason = (
                self._check_ownership())
            self._last_ownership_check_at = now
        self._latest_health = self._build_health(now)
        state = self.policy.evaluate(self._latest_health, now)
        if state == OWNERSHIP_FAULT:
            self.policy.last_reason = self._ownership_reason
        self._publish_state()
        self._publish_state_alarm()

    def _build_health(self, now):
        ownership_valid = self._ownership_valid
        if (self._patrol_expected_active
                and _age(now, self._patrol_received_at) > 0.30):
            ownership_valid = False
            self._ownership_reason = (
                'patrol status heartbeat stopped while an action was active')
        return HealthSnapshot(
            chassis_connected=self._chassis_connected,
            chassis_age_sec=_age(now, self._chassis_received_at),
            scan_age_sec=_age(now, self._scan_received_at),
            odom_age_sec=_age(now, self._odom_received_at),
            tf_complete=self._tf_complete(),
            ownership_valid=ownership_valid,
        )

    def _tf_complete(self):
        required = [
            ('odom', 'base_footprint'),
            ('base_footprint', 'base_link'),
            ('base_link', 'laser_link'),
        ]
        if self.runtime_mode in {'mapping', 'navigation'}:
            required.append(('map', 'odom'))
        return all(self._has_transform(target, source)
                   for target, source in required)

    def _has_transform(self, target, source):
        try:
            self.tf_buffer.lookup_transform(target, source, Time())
            return True
        except TransformException:
            return False

    def _check_ownership(self):
        for topic, expected in self.expected_publishers.items():
            publishers = self.get_publishers_info_by_topic(topic)
            names = [str(item.node_name).lstrip('/') for item in publishers]
            if names != [expected.lstrip('/')]:
                return False, '{} publishers are {}, expected [{}]'.format(
                    topic, names, expected)

        nodes = {name.lstrip('/') for name in self.get_node_names()}
        has_amcl = 'amcl' in nodes
        has_cartographer = 'cartographer_node' in nodes
        if has_amcl and has_cartographer:
            return False, 'AMCL and Cartographer are running together'
        if self.runtime_mode == 'base' and (has_amcl or has_cartographer):
            return False, 'base mode must not own map to odom'
        if self.runtime_mode == 'mapping' and not has_cartographer:
            return False, 'mapping mode requires cartographer_node'
        if self.runtime_mode == 'navigation' and not has_amcl:
            return False, 'navigation mode requires amcl'
        return True, 'ownership matches runtime mode'

    def _reset_callback(self, _request, response):
        now = time.monotonic()
        if self.real_low_battery_enabled and self.battery.triggered:
            response.success = False
            response.message = (
                'battery has not recovered to {:.2f} V'.format(
                    self.battery.recovery_v))
            return response
        success, reason = self.policy.reset(
            self._build_health(now), now,
            action_active=self._patrol_active(now),
            output_is_zero=self._output_is_zero,
        )
        response.success = success
        response.message = reason
        self._publish_state(force=True)
        self._publish_state_alarm()
        return response

    def _simulate_low_battery_callback(self, _request, response):
        now = time.monotonic()
        ok, reason = self._return_preconditions(now)
        if not ok:
            response.success = False
            response.message = reason
            return response
        success, reason = self.policy.request_low_battery_return(
            self._build_health(now), now)
        response.success = success
        response.message = reason
        self._publish_state(force=True)
        return response

    def _return_preconditions(self, now):
        if self.runtime_mode != 'navigation':
            return False, 'return-home requires navigation mode'
        if not self._has_transform('map', 'base_footprint'):
            return False, 'localization transform map to base_footprint is missing'
        if _age(now, self._patrol_received_at) > 1.0:
            return False, 'patrol status is unavailable'
        if not isinstance(self._patrol_status, dict):
            return False, 'patrol status is invalid'
        if not self._patrol_status.get('route_configured', False):
            return False, 'Home route is not configured'
        return True, 'return-home preconditions pass'

    def _patrol_active(self, now):
        if _age(now, self._patrol_received_at) > 0.30:
            return False
        if not isinstance(self._patrol_status, dict):
            return False
        return self._patrol_status.get('state') in {
            NAVIGATING, ARRIVED, WAITING, NEXT_GOAL, CANCELLING}

    def _publish_state(self, force=False):
        now = time.monotonic()
        changed = self.policy.state != self._last_published_state
        if force or changed or now - self._last_state_publish_at >= 0.10:
            self.state_publisher.publish(String(data=self.policy.state))
            self._last_published_state = self.policy.state
            self._last_state_publish_at = now

    def _publish_state_alarm(self):
        info = _state_alarm(self.policy.state, self.policy.last_reason)
        if self._active_state_alarm and (
                info is None or info[1] != self._active_state_alarm[1]):
            severity, code, old_state, _ = self._active_state_alarm
            self.alarms.publish(
                severity, code, old_state,
                '{} condition cleared'.format(code), active=False)
            self._active_state_alarm = None
        if info is not None:
            severity, code, state, message = info
            self.alarms.publish(severity, code, state, message)
            self._active_state_alarm = info


def _age(now, received_at):
    if received_at is None:
        return math.inf
    age = float(now) - float(received_at)
    return age if age >= 0.0 else math.inf


def _state_alarm(state, reason):
    mapping = {
        ESTOP: (CRITICAL, 'ESTOP_ACTIVE'),
        CHASSIS_FAULT: (CRITICAL, 'CHASSIS_DISCONNECTED'),
        SENSOR_FAULT: (ERROR, 'SCAN_STALE'),
        ODOM_TF_FAULT: (CRITICAL, 'ODOM_TF_STALE'),
        OWNERSHIP_FAULT: (CRITICAL, 'OWNERSHIP_CONFLICT'),
        LOW_BATTERY_RETURN: (ERROR, 'LOW_BATTERY_RETURN'),
        RETURNED_HOME: (INFO, 'RETURNED_HOME'),
        RETURN_FAILED: (CRITICAL, 'RETURN_HOME_FAILED'),
    }
    if state not in mapping or state in {READY, INITIALIZING}:
        return None
    severity, code = mapping[state]
    return severity, code, state, reason or code


def main(args=None):
    """Run the safety supervisor."""
    rclpy.init(args=args)
    node = SafetyManager()
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
