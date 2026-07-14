#!/usr/bin/env python3
"""Run bounded D1 motion-gate probes after explicit operator approval."""

import argparse
import json
import math
import os
import time

from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Imu
from std_msgs.msg import Bool, String
from std_srvs.srv import Trigger


APPROVAL_TOKEN = 'AREA_CLEAR_AND_ESTOP_READY'
LINEAR_LIMIT = 0.10
ANGULAR_LIMIT = 0.40
LINEAR_PULSE_SEC = 2.00
ANGULAR_PULSE_SEC = 2.00
EPSILON = 1e-4


class D1MotionProbe(Node):
    """Publish tightly bounded commands and retain timestamped observations."""

    def __init__(self):
        super().__init__('d1_motion_gate_probe')
        self.manual_publisher = self.create_publisher(
            Twist, '/cmd_vel_manual', 10)
        self.navigation_publisher = self.create_publisher(
            Twist, '/cmd_vel_nav', 10)
        self.estop_publisher = self.create_publisher(
            Bool, '/safety/estop', 10)
        self.reset_client = self.create_client(Trigger, '/safety/reset')

        self.output_events = []
        self.source_events = []
        self.safety_events = []
        self.connected_events = []
        self.odom_events = []
        self.raw_odom_events = []
        self.raw_velocity_events = []
        self.imu_events = []
        self.raw_imu_events = []
        self.attitude_events = []
        self.alarm_events = []
        self.scenario_diagnostics = {}
        self.nonzero_input_sent = False

        self.create_subscription(
            # Match the hardware boundary depth so stop-latency evidence is
            # not inflated by replaying queued pre-fault non-zero commands.
            Twist, '/cmd_vel', self._output_callback, 1)
        self.create_subscription(
            String, '/control/active_source', self._source_callback, 50)
        self.create_subscription(
            String, '/safety/state', self._safety_callback, 50)
        self.create_subscription(
            Bool, '/chassis/connected', self._connected_callback, 50)
        self.create_subscription(
            Odometry, '/odom', self._odom_callback, 100)
        self.create_subscription(
            Odometry, '/odom_raw', self._raw_odom_callback, 100)
        self.create_subscription(
            Twist, '/vel_raw', self._raw_velocity_callback, 100)
        self.create_subscription(
            Imu, '/imu/data', self._imu_callback, 100)
        self.create_subscription(
            Imu, '/imu/data_raw', self._raw_imu_callback, 100)
        self.create_subscription(
            Imu, '/imu/attitude', self._attitude_callback, 100)
        self.create_subscription(
            String, '/alarm_events', self._alarm_callback, 100)

    def preflight(self):
        """Require a healthy, stationary, uniquely owned safe-base graph."""
        deadline = time.monotonic() + 12.0
        while time.monotonic() < deadline:
            rclpy.spin_once(self, timeout_sec=0.05)
            if (self.safety_events
                    and self.source_events
                    and self.connected_events
                    and self.output_events
                    and self.odom_events
                    and self.raw_odom_events
                    and self.raw_velocity_events
                    and self.imu_events
                    and self.raw_imu_events
                    and self.attitude_events
                    and self.safety_events[-1][1] == 'READY'
                    and self.source_events[-1][1] == 'NONE'
                    and self.connected_events[-1][1]
                    and self.managed_publishers_match()):
                break
        else:
            raise RuntimeError(
                'preflight requires READY, NONE, connected, complete '
                'odometry feedback and unique managed publishers')

        publishers = self.managed_publishers()

        stationary_started = time.time()
        self.spin_for(0.50)
        recent = self.outputs_after(stationary_started)
        if len(recent) < 5 or any(not _is_zero(event[1:]) for event in recent):
            raise RuntimeError('preflight output was not continuously zero')
        return {
            'managed_publishers': publishers,
            'initial_safety_state': self.safety_events[-1][1],
            'initial_source': self.source_events[-1][1],
            'initial_connected': self.connected_events[-1][1],
            'odom_samples': len(self.odom_events),
            'odom_raw_samples': len(self.raw_odom_events),
            'vel_raw_samples': len(self.raw_velocity_events),
            'imu_samples': len(self.imu_events),
            'imu_raw_samples': len(self.raw_imu_events),
            'imu_attitude_samples': len(self.attitude_events),
            'stationary_samples': len(recent),
        }

    def managed_publishers(self):
        """Return normalized owner names for every pre-motion data path."""
        return {
            topic: sorted(
                str(info.node_name).lstrip('/')
                for info in self.get_publishers_info_by_topic(topic))
            for topic in (
                '/cmd_vel', '/odom', '/odom_raw', '/vel_raw', '/scan')
        }

    def managed_publishers_match(self):
        expected = {
            '/cmd_vel': ['cmd_vel_arbiter'],
            '/odom': ['ekf_filter_node'],
            '/odom_raw': ['base_node_X3'],
            '/vel_raw': ['driver_node'],
            '/scan': ['sllidar_node'],
        }
        return self.managed_publishers() == expected

    def run_scenario(self, arguments):
        """Dispatch one bounded scenario."""
        if arguments.scenario == 'preflight':
            return {'motion_command_sent': False}
        if arguments.scenario == 'linear':
            return self.run_linear()
        if arguments.scenario == 'angular':
            return self.run_angular()
        if arguments.scenario == 'timeout':
            return self.run_timeout()
        if arguments.scenario == 'source_switch':
            return self.run_source_switch()
        if arguments.scenario == 'estop':
            return self.run_estop()
        if arguments.scenario == 'external_fault':
            return self.run_external_fault(
                arguments.expected_state, arguments.trigger_file)
        raise RuntimeError('unsupported scenario')

    def run_linear(self):
        """Apply one bounded forward pulse and explicitly stop."""
        started = time.time()
        odom_start = self.latest_odom()
        raw_odom_start = self.latest_raw_odom()
        self.publish_for(
            LINEAR_PULSE_SEC,
            manual=_twist(linear_x=LINEAR_LIMIT))
        stop_requested = time.time()
        self.publish_for(0.45, manual=Twist())
        self.spin_for(0.40)
        finished = time.time()
        odom_end = self.latest_odom()
        raw_odom_end = self.latest_raw_odom()

        motion = self.nonzero_outputs_between(started, stop_requested)
        stop_latency = self.zero_latency_after(stop_requested)
        odom = _odom_delta(odom_start, odom_end)
        raw_odom = _odom_delta(raw_odom_start, raw_odom_end)
        self.scenario_diagnostics = self.motion_diagnostics(
            started, finished, odom, raw_odom)
        if not motion:
            raise RuntimeError('linear pulse never reached /cmd_vel')
        if max(abs(event[1]) for event in motion) > LINEAR_LIMIT + EPSILON:
            raise RuntimeError('linear pulse exceeded configured limit')
        if any(abs(event[2]) > EPSILON or abs(event[3]) > EPSILON
               for event in motion):
            raise RuntimeError('linear pulse contained lateral/angular motion')
        if stop_latency is None or stop_latency > 0.20:
            raise RuntimeError('explicit linear stop exceeded 0.20 seconds')

        if odom['distance_m'] < 0.005:
            raise RuntimeError(
                'linear odometry response was below 5 mm; '
                'see diagnostics for /vel_raw and /odom_raw evidence')
        return {
            'motion_command_sent': True,
            'requested_linear_x': LINEAR_LIMIT,
            'pulse_sec': LINEAR_PULSE_SEC,
            'max_output_linear_x': round(
                max(abs(event[1]) for event in motion), 4),
            'explicit_stop_latency_sec': round(stop_latency, 3),
            'odom': odom,
            'odom_raw': raw_odom,
        }

    def run_angular(self):
        """Apply one bounded yaw pulse and explicitly stop."""
        started = time.time()
        odom_start = self.latest_odom()
        raw_odom_start = self.latest_raw_odom()
        self.publish_for(
            ANGULAR_PULSE_SEC,
            manual=_twist(angular_z=ANGULAR_LIMIT))
        stop_requested = time.time()
        self.publish_for(0.45, manual=Twist())
        self.spin_for(0.40)
        finished = time.time()
        odom_end = self.latest_odom()
        raw_odom_end = self.latest_raw_odom()

        motion = self.nonzero_outputs_between(started, stop_requested)
        stop_latency = self.zero_latency_after(stop_requested)
        odom = _odom_delta(odom_start, odom_end)
        raw_odom = _odom_delta(raw_odom_start, raw_odom_end)
        self.scenario_diagnostics = self.motion_diagnostics(
            started, finished, odom, raw_odom)
        if not motion:
            raise RuntimeError('angular pulse never reached /cmd_vel')
        if max(abs(event[3]) for event in motion) > ANGULAR_LIMIT + EPSILON:
            raise RuntimeError('angular pulse exceeded configured limit')
        if any(abs(event[1]) > EPSILON or abs(event[2]) > EPSILON
               for event in motion):
            raise RuntimeError('angular pulse contained linear motion')
        if stop_latency is None or stop_latency > 0.20:
            raise RuntimeError('explicit angular stop exceeded 0.20 seconds')

        if abs(odom['yaw_delta_rad']) < 0.02:
            raise RuntimeError(
                'angular odometry response was below 0.02 rad; '
                'see diagnostics for /vel_raw and /odom_raw evidence')
        return {
            'motion_command_sent': True,
            'requested_angular_z': ANGULAR_LIMIT,
            'pulse_sec': ANGULAR_PULSE_SEC,
            'max_output_angular_z': round(
                max(abs(event[3]) for event in motion), 4),
            'explicit_stop_latency_sec': round(stop_latency, 3),
            'odom': odom,
            'odom_raw': raw_odom,
        }

    def run_timeout(self):
        """Stop publishing a live manual request and measure stale timeout."""
        started = time.time()
        last_input_at = self.publish_for(
            0.55, manual=_twist(linear_x=LINEAR_LIMIT))
        self.spin_for(0.85)

        motion = self.nonzero_outputs_between(started, last_input_at + 0.01)
        if not motion:
            raise RuntimeError('timeout probe never reached /cmd_vel')
        stop_latency = self.zero_latency_after(last_input_at)
        if stop_latency is None or stop_latency > 0.40:
            raise RuntimeError('command timeout exceeded 0.40 seconds')
        if not self.source_seen('NONE', after=last_input_at):
            raise RuntimeError('source did not return to NONE after timeout')
        if not self.alarm_contains('CMD_TIMEOUT', after=last_input_at):
            raise RuntimeError('CMD_TIMEOUT alarm was not observed')
        self.publish_for(0.35, manual=Twist())
        return {
            'motion_command_sent': True,
            'requested_linear_x': LINEAR_LIMIT,
            'command_timeout_latency_sec': round(stop_latency, 3),
            'source_after_timeout': self.source_events[-1][1],
            'cmd_timeout_alarm_seen': True,
        }

    def run_source_switch(self):
        """Switch from navigation to same-direction manual control via zero."""
        nav_started = time.time()
        self.publish_for(0.55, navigation=_twist(linear_x=0.03))
        if not self.source_seen('NAVIGATION', after=nav_started):
            raise RuntimeError('navigation source was not acquired')

        switch_started = time.time()
        self.publish_for(
            0.65,
            manual=_twist(linear_x=0.02),
            navigation=_twist(linear_x=0.03))
        if not self.source_seen('ZEROING', after=switch_started):
            raise RuntimeError('zero-before-switch source was not observed')
        if not self.source_seen('MANUAL', after=switch_started):
            raise RuntimeError('manual source was not acquired')
        zeroing_at = self.first_source_time('ZEROING', switch_started)
        manual_at = self.first_source_time('MANUAL', switch_started)
        if zeroing_at > manual_at:
            raise RuntimeError('ZEROING was reported after MANUAL activation')
        if not any(
                switch_started <= event[0] <= manual_at
                and _is_zero(event[1:])
                for event in self.output_events):
            raise RuntimeError('no zero output occurred between sources')

        manual_stopped = time.time()
        self.publish_for(0.60, navigation=_twist(linear_x=0.03))
        if self.source_seen('NAVIGATION', after=manual_stopped + 0.30):
            raise RuntimeError('old navigation resumed after manual takeover')
        outputs = self.outputs_after(manual_stopped + 0.35)
        if not outputs or any(not _is_zero(event[1:]) for event in outputs):
            raise RuntimeError('navigation inhibit did not preserve zero output')
        return {
            'motion_command_sent': True,
            'navigation_linear_x': 0.03,
            'manual_linear_x': 0.02,
            'zero_before_switch': True,
            'manual_priority': True,
            'old_navigation_resumed': False,
        }

    def run_estop(self):
        """Assert e-stop while a fresh manual command is still arriving."""
        motion_started = time.time()
        self.publish_for(0.50, manual=_twist(linear_x=LINEAR_LIMIT))
        if not self.nonzero_outputs_between(motion_started, time.time()):
            raise RuntimeError('e-stop probe never reached /cmd_vel')

        trigger_at = time.time()
        self.publish_for(
            0.25,
            manual=_twist(linear_x=LINEAR_LIMIT),
            estop=True)
        self.publish_for(
            0.35,
            manual=_twist(linear_x=LINEAR_LIMIT),
            estop=True)
        stop_latency = self.zero_latency_after(trigger_at)
        if stop_latency is None or stop_latency > 0.50:
            raise RuntimeError('e-stop output latency exceeded 0.50 seconds')
        if not self.safety_seen('ESTOP', after=trigger_at):
            raise RuntimeError('ESTOP safety state was not observed')
        if not self.alarm_contains('ESTOP_ACTIVE', after=trigger_at):
            raise RuntimeError('ESTOP_ACTIVE alarm was not observed')

        self.publish_for(0.35, manual=Twist(), estop=False)
        self.spin_for(0.20)
        if self.safety_events[-1][1] != 'ESTOP':
            raise RuntimeError('e-stop latch cleared without explicit reset')
        response = self.call_reset()
        self.publish_for(0.35, manual=Twist(), estop=False)
        self.spin_for(0.40)
        if not response.success or not self.safety_seen('READY', after=trigger_at):
            raise RuntimeError(
                'e-stop reset failed: {}'.format(response.message))
        return {
            'motion_command_sent': True,
            'requested_linear_x': LINEAR_LIMIT,
            'estop_stop_latency_sec': round(stop_latency, 3),
            'estop_latched_after_release': True,
            'reset_success': bool(response.success),
            'reset_message': response.message,
        }

    def run_external_fault(self, expected_state, trigger_file):
        """Keep a bounded request live while an external fault is injected."""
        if not expected_state or not trigger_file:
            raise RuntimeError(
                'external_fault requires --expected-state and --trigger-file')
        motion_started = time.time()
        self.publish_for(0.50, manual=_twist(linear_x=LINEAR_LIMIT))
        if not self.nonzero_outputs_between(motion_started, time.time()):
            raise RuntimeError('external-fault probe never reached /cmd_vel')
        print('READY_FOR_FAULT', flush=True)

        trigger_at = None
        trigger_deadline = time.monotonic() + 12.0
        while time.monotonic() < trigger_deadline and trigger_at is None:
            self.manual_publisher.publish(_twist(linear_x=LINEAR_LIMIT))
            rclpy.spin_once(self, timeout_sec=0.02)
            trigger_at = _read_epoch(trigger_file)
            time.sleep(0.02)
        if trigger_at is None:
            raise RuntimeError('external fault trigger was not received')

        state_seen_at = None
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            self.manual_publisher.publish(_twist(linear_x=LINEAR_LIMIT))
            rclpy.spin_once(self, timeout_sec=0.02)
            state_seen_at = self.first_safety_time(expected_state, trigger_at)
            zero_latency = self.zero_latency_after(trigger_at)
            if state_seen_at is not None and zero_latency is not None:
                break
            time.sleep(0.02)
        else:
            raise RuntimeError(
                'fault did not produce {} and zero output'.format(
                    expected_state))
        self.scenario_diagnostics = {
            'expected_state': expected_state,
            'chassis_disconnected_latency_sec': _rounded_latency(
                _first_event_time(
                    self.connected_events, False, trigger_at), trigger_at),
            'state_transition_latency_sec': round(
                state_seen_at - trigger_at, 3),
            'blocked_source_latency_sec': _rounded_latency(
                self.first_source_time('BLOCKED', trigger_at), trigger_at),
            'stop_latency_sec': round(zero_latency, 3),
        }
        if zero_latency > 0.50:
            raise RuntimeError('external fault stop exceeded 0.50 seconds')
        self.publish_for(0.40, manual=Twist())
        return {
            'motion_command_sent': True,
            'requested_linear_x': LINEAR_LIMIT,
            'expected_state': expected_state,
            'state_transition_latency_sec': round(
                state_seen_at - trigger_at, 3),
            'stop_latency_sec': round(zero_latency, 3),
            'connected_after_fault': (
                self.connected_events[-1][1]
                if self.connected_events else None),
        }

    def finish_zero(self):
        """End every motion scenario with repeated explicit upstream zeros."""
        if self.nonzero_input_sent:
            # Manual zero has priority over navigation and avoids creating a
            # second source transition during cleanup.
            self.publish_for(0.45, manual=Twist())
        self.spin_for(0.45)

    def final_summary(self):
        """Return the final safety observations without changing state."""
        recent = self.output_events[-10:]
        return {
            'safety_state': (
                self.safety_events[-1][1] if self.safety_events else None),
            'active_source': (
                self.source_events[-1][1] if self.source_events else None),
            'chassis_connected': (
                self.connected_events[-1][1]
                if self.connected_events else None),
            'cmd_vel_samples': len(self.output_events),
            'nonzero_cmd_vel_samples': sum(
                1 for event in self.output_events
                if not _is_zero(event[1:])),
            'feedback_samples': {
                'odom': len(self.odom_events),
                'odom_raw': len(self.raw_odom_events),
                'vel_raw': len(self.raw_velocity_events),
                'imu': len(self.imu_events),
                'imu_raw': len(self.raw_imu_events),
                'imu_attitude': len(self.attitude_events),
            },
            'last_ten_outputs_zero': (
                len(recent) == 10
                and all(_is_zero(event[1:]) for event in recent)),
            'publishers': self.managed_publishers(),
            'recent_alarm_events': [
                payload for _, payload in self.alarm_events[-5:]],
        }

    def publish_for(self, duration_sec, *, manual=None,
                    navigation=None, estop=None):
        """Publish selected values at 25 Hz for a bounded duration."""
        deadline = time.monotonic() + float(duration_sec)
        next_publish = time.monotonic()
        last_publish_at = None
        while time.monotonic() < deadline:
            now = time.monotonic()
            if now >= next_publish:
                if manual is not None:
                    self.manual_publisher.publish(manual)
                    if not _message_is_zero(manual):
                        self.nonzero_input_sent = True
                if navigation is not None:
                    self.navigation_publisher.publish(navigation)
                    if not _message_is_zero(navigation):
                        self.nonzero_input_sent = True
                if estop is not None:
                    self.estop_publisher.publish(Bool(data=bool(estop)))
                last_publish_at = time.time()
                next_publish += 0.04
            rclpy.spin_once(self, timeout_sec=0.01)
        return last_publish_at or time.time()

    def spin_for(self, duration_sec):
        deadline = time.monotonic() + float(duration_sec)
        while time.monotonic() < deadline:
            rclpy.spin_once(self, timeout_sec=0.02)

    def call_reset(self):
        if not self.reset_client.wait_for_service(timeout_sec=2.0):
            raise RuntimeError('/safety/reset is unavailable')
        future = self.reset_client.call_async(Trigger.Request())
        deadline = time.monotonic() + 2.0
        while not future.done() and time.monotonic() < deadline:
            rclpy.spin_once(self, timeout_sec=0.02)
        if not future.done() or future.result() is None:
            raise RuntimeError('/safety/reset timed out')
        return future.result()

    def outputs_after(self, timestamp):
        return [event for event in self.output_events if event[0] >= timestamp]

    def nonzero_outputs_between(self, started, ended):
        return [
            event for event in self.output_events
            if started <= event[0] <= ended and not _is_zero(event[1:])]

    def zero_latency_after(self, timestamp):
        for event in self.output_events:
            if event[0] >= timestamp and _is_zero(event[1:]):
                return event[0] - timestamp
        return None

    def source_seen(self, value, after=0.0):
        return self.first_source_time(value, after) is not None

    def safety_seen(self, value, after=0.0):
        return self.first_safety_time(value, after) is not None

    def first_source_time(self, value, after=0.0):
        return _first_event_time(self.source_events, value, after)

    def first_safety_time(self, value, after=0.0):
        return _first_event_time(self.safety_events, value, after)

    def alarm_contains(self, text, after=0.0):
        return any(
            timestamp >= after and text in payload
            for timestamp, payload in self.alarm_events)

    def latest_odom(self):
        if not self.odom_events:
            raise RuntimeError('odometry is unavailable')
        return self.odom_events[-1]

    def latest_raw_odom(self):
        if not self.raw_odom_events:
            raise RuntimeError('raw odometry is unavailable')
        return self.raw_odom_events[-1]

    def motion_diagnostics(self, started, finished, odom, raw_odom):
        """Aggregate command and chassis feedback even when a gate fails."""
        outputs = _events_between(self.output_events, started, finished)
        velocities = _events_between(
            self.raw_velocity_events, started, finished)
        filtered_odometry = _events_between(
            self.odom_events, started, finished)
        raw_odometry = _events_between(
            self.raw_odom_events, started, finished)
        filtered_imu = _events_between(
            self.imu_events, started, finished)
        raw_imu = _events_between(
            self.raw_imu_events, started, finished)
        onboard_attitude = _events_between(
            self.attitude_events, started, finished)
        return {
            'window_sec': round(finished - started, 3),
            'cmd_vel': _vector_diagnostics(outputs),
            'vel_raw': _vector_diagnostics(velocities),
            'odom_twist': _odom_twist_diagnostics(filtered_odometry),
            'odom_raw_twist': _odom_twist_diagnostics(raw_odometry),
            'imu': _imu_diagnostics(filtered_imu),
            'imu_raw': _imu_diagnostics(raw_imu),
            'imu_attitude': _imu_diagnostics(onboard_attitude),
            'odom_delta': odom,
            'odom_raw_delta': raw_odom,
        }

    def _output_callback(self, message):
        self.output_events.append((
            time.time(),
            float(message.linear.x),
            float(message.linear.y),
            float(message.angular.z),
        ))

    def _source_callback(self, message):
        self.source_events.append((time.time(), message.data))

    def _safety_callback(self, message):
        self.safety_events.append((time.time(), message.data))

    def _connected_callback(self, message):
        self.connected_events.append((time.time(), bool(message.data)))

    def _odom_callback(self, message):
        self.odom_events.append(_odometry_event(message))

    def _raw_odom_callback(self, message):
        self.raw_odom_events.append(_odometry_event(message))

    def _raw_velocity_callback(self, message):
        self.raw_velocity_events.append((
            time.time(),
            float(message.linear.x),
            float(message.linear.y),
            float(message.angular.z),
        ))

    def _imu_callback(self, message):
        self.imu_events.append(_imu_event(message))

    def _raw_imu_callback(self, message):
        self.raw_imu_events.append(_imu_event(message))

    def _attitude_callback(self, message):
        self.attitude_events.append(_imu_event(message))

    def _alarm_callback(self, message):
        self.alarm_events.append((time.time(), message.data))


def _parse_arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument('--approval-token', required=True)
    parser.add_argument('--scenario', required=True, choices=(
        'preflight', 'linear', 'angular', 'timeout',
        'source_switch', 'estop', 'external_fault'))
    parser.add_argument('--expected-state', default='')
    parser.add_argument('--trigger-file', default='')
    result = parser.parse_args()
    if result.approval_token != APPROVAL_TOKEN:
        parser.error('explicit area-clear/e-stop approval token is required')
    return result


def _twist(*, linear_x=0.0, linear_y=0.0, angular_z=0.0):
    if abs(linear_x) > LINEAR_LIMIT + EPSILON:
        raise ValueError('linear_x exceeds D1 limit')
    if abs(linear_y) > LINEAR_LIMIT + EPSILON:
        raise ValueError('linear_y exceeds D1 limit')
    if abs(angular_z) > ANGULAR_LIMIT + EPSILON:
        raise ValueError('angular_z exceeds D1 limit')
    message = Twist()
    message.linear.x = float(linear_x)
    message.linear.y = float(linear_y)
    message.angular.z = float(angular_z)
    return message


def _is_zero(values):
    return all(math.isfinite(value) and abs(value) <= EPSILON
               for value in values)


def _message_is_zero(message):
    return _is_zero((
        float(message.linear.x),
        float(message.linear.y),
        float(message.angular.z),
    ))


def _first_event_time(events, value, after):
    for timestamp, observed in events:
        if timestamp >= after and observed == value:
            return timestamp
    return None


def _rounded_latency(timestamp, trigger_at):
    if timestamp is None:
        return None
    return round(timestamp - trigger_at, 3)


def _read_epoch(path):
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, 'r', encoding='ascii') as stream:
            value = float(stream.read().strip())
        return value if math.isfinite(value) else None
    except (OSError, TypeError, ValueError):
        return None


def _yaw(x, y, z, w):
    sin_yaw = 2.0 * (w * z + x * y)
    cos_yaw = 1.0 - 2.0 * (y * y + z * z)
    return math.atan2(sin_yaw, cos_yaw)


def _odom_delta(start, end):
    _, start_x, start_y, start_yaw, _, _, _ = start
    _, end_x, end_y, end_yaw, _, _, _ = end
    delta_x = end_x - start_x
    delta_y = end_y - start_y
    yaw_delta = math.atan2(
        math.sin(end_yaw - start_yaw),
        math.cos(end_yaw - start_yaw))
    return {
        'delta_x_m': round(delta_x, 6),
        'delta_y_m': round(delta_y, 6),
        'distance_m': round(math.hypot(delta_x, delta_y), 6),
        'yaw_delta_rad': round(yaw_delta, 6),
    }


def _odometry_event(message):
    orientation = message.pose.pose.orientation
    return (
        time.time(),
        float(message.pose.pose.position.x),
        float(message.pose.pose.position.y),
        _yaw(orientation.x, orientation.y, orientation.z, orientation.w),
        float(message.twist.twist.linear.x),
        float(message.twist.twist.linear.y),
        float(message.twist.twist.angular.z),
    )


def _imu_event(message):
    orientation = message.orientation
    return (
        time.time(),
        _yaw(orientation.x, orientation.y, orientation.z, orientation.w),
        float(message.angular_velocity.x),
        float(message.angular_velocity.y),
        float(message.angular_velocity.z),
    )


def _events_between(events, started, finished):
    return [
        event for event in events
        if started <= event[0] <= finished]


def _vector_diagnostics(events):
    vectors = [event[1:4] for event in events]
    return {
        'samples': len(vectors),
        'nonzero_samples': sum(
            1 for vector in vectors if not _is_zero(vector)),
        'max_abs_linear_x': round(
            max((abs(vector[0]) for vector in vectors), default=0.0), 6),
        'max_abs_linear_y': round(
            max((abs(vector[1]) for vector in vectors), default=0.0), 6),
        'max_abs_angular_z': round(
            max((abs(vector[2]) for vector in vectors), default=0.0), 6),
        'min_linear_x': round(
            min((vector[0] for vector in vectors), default=0.0), 6),
        'max_linear_x': round(
            max((vector[0] for vector in vectors), default=0.0), 6),
    }


def _odom_twist_diagnostics(events):
    twists = [(event[4], event[5], event[6]) for event in events]
    return {
        'samples': len(twists),
        'nonzero_samples': sum(
            1 for twist in twists if not _is_zero(twist)),
        'max_abs_linear_x': round(
            max((abs(twist[0]) for twist in twists), default=0.0), 6),
        'max_abs_linear_y': round(
            max((abs(twist[1]) for twist in twists), default=0.0), 6),
        'max_abs_angular_z': round(
            max((abs(twist[2]) for twist in twists), default=0.0), 6),
        'min_linear_x': round(
            min((twist[0] for twist in twists), default=0.0), 6),
        'max_linear_x': round(
            max((twist[0] for twist in twists), default=0.0), 6),
    }


def _imu_diagnostics(events):
    yaw_delta = 0.0
    if len(events) >= 2:
        yaw_delta = math.atan2(
            math.sin(events[-1][1] - events[0][1]),
            math.cos(events[-1][1] - events[0][1]))
    return {
        'samples': len(events),
        'yaw_delta_rad': round(yaw_delta, 6),
        'max_abs_angular_x': round(
            max((abs(event[2]) for event in events), default=0.0), 6),
        'max_abs_angular_y': round(
            max((abs(event[3]) for event in events), default=0.0), 6),
        'max_abs_angular_z': round(
            max((abs(event[4]) for event in events), default=0.0), 6),
    }


def main():
    arguments = _parse_arguments()
    rclpy.init()
    node = D1MotionProbe()
    result = {
        'schema': 'D1MotionGateProbe/v2',
        'scenario': arguments.scenario,
        'approval': 'area clear; operator at emergency stop',
        'limits': {
            'linear_mps': LINEAR_LIMIT,
            'angular_rps': ANGULAR_LIMIT,
        },
    }
    exit_code = 0
    try:
        result['preflight'] = node.preflight()
        result['observations'] = node.run_scenario(arguments)
        result['passed'] = True
    except Exception as exc:  # Safety probe must report and zero on every failure.
        result['passed'] = False
        result['error'] = '{}: {}'.format(type(exc).__name__, exc)
        exit_code = 2
    finally:
        if node.scenario_diagnostics:
            result['diagnostics'] = node.scenario_diagnostics
        try:
            node.finish_zero()
        except Exception as exc:
            result['passed'] = False
            result['zero_cleanup_error'] = '{}: {}'.format(
                type(exc).__name__, exc)
            exit_code = 3
        result['final'] = node.final_summary()
        if not result['final']['last_ten_outputs_zero']:
            result['passed'] = False
            result['final_zero_error'] = 'last ten /cmd_vel samples were not zero'
            exit_code = 4
        print(json.dumps(result, indent=2, sort_keys=True), flush=True)
        node.destroy_node()
        rclpy.shutdown()
    raise SystemExit(exit_code)


if __name__ == '__main__':
    main()
