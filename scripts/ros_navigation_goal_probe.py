#!/usr/bin/env python3
"""Bounded AMCL initialization and Nav2 goal acceptance probe for Foxy."""

import argparse
import json
import math
import sys
import time

from action_msgs.msg import GoalStatus
from geometry_msgs.msg import PoseWithCovarianceStamped, Twist
from nav2_msgs.action import NavigateToPose
from nav_msgs.msg import Odometry
import rclpy
from rclpy.action import ActionClient
from rclpy.node import Node
from rclpy.time import Time
from sensor_msgs.msg import LaserScan
from std_msgs.msg import Bool, String
from std_srvs.srv import Trigger
from tf2_ros import Buffer, TransformException, TransformListener


APPROVAL_TOKEN = 'APPROVED_CORRIDOR_MOTION'
STATUS_NAMES = {
    GoalStatus.STATUS_UNKNOWN: 'UNKNOWN',
    GoalStatus.STATUS_ACCEPTED: 'ACCEPTED',
    GoalStatus.STATUS_EXECUTING: 'EXECUTING',
    GoalStatus.STATUS_CANCELING: 'CANCELING',
    GoalStatus.STATUS_SUCCEEDED: 'SUCCEEDED',
    GoalStatus.STATUS_CANCELED: 'CANCELED',
    GoalStatus.STATUS_ABORTED: 'ABORTED',
}


def _yaw_from_quaternion(quaternion):
    siny = 2.0 * (
        quaternion.w * quaternion.z + quaternion.x * quaternion.y)
    cosy = 1.0 - 2.0 * (
        quaternion.y * quaternion.y + quaternion.z * quaternion.z)
    return math.atan2(siny, cosy)


def _angle_error(actual, expected):
    return abs(math.atan2(
        math.sin(actual - expected), math.cos(actual - expected)))


class NavigationGoalProbe(Node):
    """Own all bounded-test state while leaving velocity ownership unchanged."""

    def __init__(self):
        super().__init__('navigation_goal_acceptance_probe')
        self.safety_state = None
        self.chassis_connected = None
        self.last_scan_at = None
        self.last_odom_at = None
        self.last_amcl_at = None
        self.nonzero_output_count = 0
        self.max_linear = 0.0
        self.max_angular = 0.0
        self.feedback_count = 0
        self.safety_history = []

        self.initial_pose_publisher = self.create_publisher(
            PoseWithCovarianceStamped, '/initialpose', 10)
        self.manual_publisher = self.create_publisher(
            Twist, '/cmd_vel_manual', 10)
        self.create_subscription(
            String, '/safety/state', self._safety_callback, 20)
        self.create_subscription(
            Bool, '/chassis/connected', self._chassis_callback, 20)
        self.create_subscription(
            LaserScan, '/scan', self._scan_callback, 20)
        self.create_subscription(
            Odometry, '/odom', self._odom_callback, 50)
        self.create_subscription(
            PoseWithCovarianceStamped, '/amcl_pose',
            self._amcl_callback, 20)
        self.create_subscription(
            Twist, '/cmd_vel', self._command_callback, 50)

        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)
        self.reset_client = self.create_client(Trigger, '/safety/reset')
        self.action_client = ActionClient(
            self, NavigateToPose, '/navigate_to_pose')

    def _safety_callback(self, message):
        self.safety_state = message.data
        if not self.safety_history or self.safety_history[-1] != message.data:
            self.safety_history.append(message.data)

    def _chassis_callback(self, message):
        self.chassis_connected = bool(message.data)

    def _scan_callback(self, _message):
        self.last_scan_at = time.monotonic()

    def _odom_callback(self, _message):
        self.last_odom_at = time.monotonic()

    def _amcl_callback(self, _message):
        self.last_amcl_at = time.monotonic()

    def _command_callback(self, message):
        linear = math.hypot(message.linear.x, message.linear.y)
        angular = abs(message.angular.z)
        if linear > 1e-9 or angular > 1e-9:
            self.nonzero_output_count += 1
        self.max_linear = max(self.max_linear, linear)
        self.max_angular = max(self.max_angular, angular)

    def _feedback_callback(self, _feedback):
        self.feedback_count += 1

    def spin_until(self, predicate, timeout_sec):
        deadline = time.monotonic() + float(timeout_sec)
        while time.monotonic() < deadline:
            rclpy.spin_once(self, timeout_sec=0.05)
            if predicate():
                return True
        return False

    def publish_initial_pose(self, x, y, yaw):
        message = PoseWithCovarianceStamped()
        message.header.frame_id = 'map'
        message.pose.pose.position.x = float(x)
        message.pose.pose.position.y = float(y)
        message.pose.pose.orientation.z = math.sin(float(yaw) / 2.0)
        message.pose.pose.orientation.w = math.cos(float(yaw) / 2.0)
        message.pose.covariance[0] = 0.05
        message.pose.covariance[7] = 0.05
        message.pose.covariance[35] = 0.10
        for _ in range(3):
            message.header.stamp = self.get_clock().now().to_msg()
            self.initial_pose_publisher.publish(message)
            self.spin_until(lambda: False, 0.25)

    def graph_gate(self, timeout_sec=10.0):
        expected = {
            '/cmd_vel': ['cmd_vel_arbiter'],
            '/scan': ['sllidar_node'],
            '/odom': ['ekf_filter_node'],
        }
        deadline = time.monotonic() + float(timeout_sec)
        actual = {}
        while time.monotonic() < deadline:
            actual = {
                topic: sorted(
                    info.node_name.lstrip('/')
                    for info in self.get_publishers_info_by_topic(topic))
                for topic in expected
            }
            if all(actual[topic] == owners
                   for topic, owners in expected.items()):
                return actual
            rclpy.spin_once(self, timeout_sec=0.10)
        raise RuntimeError(
            'publisher ownership did not converge: actual={}, expected={}'.format(
                actual, expected))

    def current_pose(self):
        try:
            transform = self.tf_buffer.lookup_transform(
                'map', 'base_footprint', Time())
        except TransformException as exc:
            raise RuntimeError(
                'map to base_footprint transform unavailable: {}'.format(exc))
        translation = transform.transform.translation
        rotation = transform.transform.rotation
        return {
            'x': float(translation.x),
            'y': float(translation.y),
            'yaw': float(_yaw_from_quaternion(rotation)),
        }

    def reset_safety(self):
        if not self.reset_client.wait_for_service(timeout_sec=5.0):
            raise RuntimeError('/safety/reset service unavailable')
        future = self.reset_client.call_async(Trigger.Request())
        if not self.spin_until(future.done, 5.0):
            raise RuntimeError('/safety/reset timed out')
        response = future.result()
        if response is None or not response.success:
            raise RuntimeError(
                '/safety/reset rejected: {}'.format(
                    response.message if response else 'no response'))
        return response.message

    def send_goal(self, x, y, yaw, timeout_sec):
        if not self.action_client.wait_for_server(timeout_sec=8.0):
            raise RuntimeError('/navigate_to_pose action server unavailable')
        goal = NavigateToPose.Goal()
        goal.pose.header.frame_id = 'map'
        goal.pose.header.stamp = self.get_clock().now().to_msg()
        goal.pose.pose.position.x = float(x)
        goal.pose.pose.position.y = float(y)
        goal.pose.pose.orientation.z = math.sin(float(yaw) / 2.0)
        goal.pose.pose.orientation.w = math.cos(float(yaw) / 2.0)

        send_future = self.action_client.send_goal_async(
            goal, feedback_callback=self._feedback_callback)
        if not self.spin_until(send_future.done, 8.0):
            raise RuntimeError('goal acceptance timed out')
        goal_handle = send_future.result()
        if goal_handle is None or not goal_handle.accepted:
            raise RuntimeError('goal was rejected')

        result_future = goal_handle.get_result_async()
        if not self.spin_until(result_future.done, timeout_sec):
            cancel_future = goal_handle.cancel_goal_async()
            self.spin_until(cancel_future.done, 5.0)
            raise TimeoutError(
                'navigation timed out after {:.1f} seconds'.format(timeout_sec))
        response = result_future.result()
        status = int(response.status)
        return status, STATUS_NAMES.get(status, str(status))

    def publish_final_zero(self):
        zero = Twist()
        for _ in range(8):
            self.manual_publisher.publish(zero)
            rclpy.spin_once(self, timeout_sec=0.05)


def _parse_arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument('--initial-x', type=float, required=True)
    parser.add_argument('--initial-y', type=float, required=True)
    parser.add_argument('--initial-yaw', type=float, required=True)
    parser.add_argument('--initialize-only', action='store_true')
    parser.add_argument('--goal-x', type=float)
    parser.add_argument('--goal-y', type=float)
    parser.add_argument('--goal-yaw', type=float)
    parser.add_argument('--approval-token', default='')
    parser.add_argument('--timeout-sec', type=float, default=45.0)
    parser.add_argument('--max-distance', type=float, default=0.50)
    parser.add_argument('--xy-tolerance', type=float, default=0.20)
    parser.add_argument('--yaw-tolerance', type=float, default=0.20)
    return parser.parse_args()


def main():
    args = _parse_arguments()
    result = {
        'schema': 'RosNavigationGoalProbe/v1',
        'initialize_only': bool(args.initialize_only),
        'passed': False,
        'failure': None,
        'goal_status': None,
    }
    node = None
    exit_code = 1
    rclpy.init()
    try:
        node = NavigationGoalProbe()
        if not node.spin_until(
                lambda: node.last_scan_at is not None
                and node.last_odom_at is not None
                and node.chassis_connected is True, 10.0):
            raise RuntimeError('scan, odom or chassis readiness timed out')
        result['publishers'] = node.graph_gate()

        node.publish_initial_pose(
            args.initial_x, args.initial_y, args.initial_yaw)
        localized = node.spin_until(
            lambda: node.last_amcl_at is not None
            and node.tf_buffer.can_transform(
                'map', 'base_footprint', Time()), 15.0)
        if not localized:
            raise RuntimeError('AMCL localization timed out')
        result['reset_message'] = node.reset_safety()
        if not node.spin_until(lambda: node.safety_state == 'READY', 5.0):
            raise RuntimeError(
                'safety did not reach READY: {}'.format(node.safety_state))
        result['start_pose'] = node.current_pose()

        if args.initialize_only:
            result['passed'] = True
            exit_code = 0
        else:
            if args.approval_token != APPROVAL_TOKEN:
                raise RuntimeError('explicit corridor motion approval token missing')
            if None in (args.goal_x, args.goal_y, args.goal_yaw):
                raise RuntimeError('goal x, y and yaw are required')
            distance = math.hypot(
                args.goal_x - result['start_pose']['x'],
                args.goal_y - result['start_pose']['y'])
            result['requested_distance_m'] = distance
            if distance > args.max_distance + 1e-9:
                raise RuntimeError(
                    'goal distance {:.3f} exceeds {:.3f} metre limit'.format(
                        distance, args.max_distance))
            status, status_name = node.send_goal(
                args.goal_x, args.goal_y, args.goal_yaw, args.timeout_sec)
            result['goal_status'] = status_name
            if status != GoalStatus.STATUS_SUCCEEDED:
                raise RuntimeError(
                    'navigation finished with {}'.format(status_name))
            node.spin_until(lambda: False, 0.5)
            result['final_pose'] = node.current_pose()
            result['xy_error_m'] = math.hypot(
                result['final_pose']['x'] - args.goal_x,
                result['final_pose']['y'] - args.goal_y)
            result['yaw_error_rad'] = _angle_error(
                result['final_pose']['yaw'], args.goal_yaw)
            if result['xy_error_m'] > args.xy_tolerance:
                raise RuntimeError('final position error exceeds tolerance')
            if result['yaw_error_rad'] > args.yaw_tolerance:
                raise RuntimeError('final yaw error exceeds tolerance')
            result['passed'] = True
            exit_code = 0
    except Exception as exc:  # bounded evidence must survive every failure
        result['failure'] = '{}: {}'.format(type(exc).__name__, exc)
    finally:
        if node is not None:
            node.publish_final_zero()
            result['safety_state'] = node.safety_state
            result['safety_history'] = node.safety_history
            result['feedback_count'] = node.feedback_count
            result['nonzero_output_count'] = node.nonzero_output_count
            result['max_output_linear_mps'] = node.max_linear
            result['max_output_angular_rps'] = node.max_angular
            node.action_client.destroy()
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
        print(json.dumps(result, indent=2, sort_keys=True))
    return exit_code


if __name__ == '__main__':
    sys.exit(main())
