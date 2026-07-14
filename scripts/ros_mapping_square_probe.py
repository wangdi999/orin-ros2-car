#!/usr/bin/env python3
"""Drive one bounded odometry-closed square while Cartographer maps."""

import argparse
import json
import math
import time

from geometry_msgs.msg import Twist
from nav_msgs.msg import OccupancyGrid, Odometry
import rclpy
from rclpy.node import Node
from std_msgs.msg import String


APPROVAL_TOKEN = 'AREA_CLEAR_AND_ESTOP_READY'
LINEAR_SPEED = 0.10
ANGULAR_SPEED = 0.40


class MappingSquareProbe(Node):
    """Publish a small square through the manual upstream command topic."""

    def __init__(self, side_meters):
        super().__init__('mapping_square_probe')
        self.side_meters = float(side_meters)
        self.manual = self.create_publisher(Twist, '/cmd_vel_manual', 1)
        self.safety_state = None
        self.odom = None
        self.map_info = None
        self.output = None
        self.nonzero_output_count = 0
        self.create_subscription(
            String, '/safety/state', self._safety_callback, 10)
        self.create_subscription(Odometry, '/odom', self._odom_callback, 10)
        self.create_subscription(
            OccupancyGrid, '/map', self._map_callback, 1)
        self.create_subscription(Twist, '/cmd_vel', self._output_callback, 1)

    def wait_ready(self):
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            rclpy.spin_once(self, timeout_sec=0.05)
            if (self.safety_state == 'READY' and self.odom is not None
                    and self.map_info is not None and self.output is not None):
                self.stop(0.50)
                if self.safety_state == 'READY' and self._output_is_zero():
                    return
        raise RuntimeError(
            'mapping preflight missing safety={!r}, odom={}, map={}, '
            'cmd_vel={}'.format(
                self.safety_state,
                self.odom is not None,
                self.map_info is not None,
                self.output is not None))

    def drive_square(self):
        legs = []
        for index in range(4):
            legs.append(self.drive_straight(index + 1))
            legs.append(self.turn_left(index + 1))
        self.stop(1.0)
        self.spin_for(2.0)
        return legs

    def drive_straight(self, index):
        start_x, start_y = self.odom[0], self.odom[1]
        started = time.time()
        deadline = time.monotonic() + max(8.0, self.side_meters / 0.06)
        distance = 0.0
        while time.monotonic() < deadline:
            self._require_ready()
            command = Twist()
            command.linear.x = LINEAR_SPEED
            self.manual.publish(command)
            rclpy.spin_once(self, timeout_sec=0.02)
            distance = math.hypot(
                self.odom[0] - start_x, self.odom[1] - start_y)
            if distance >= self.side_meters:
                break
            time.sleep(0.02)
        else:
            raise RuntimeError('straight leg {} timed out'.format(index))
        self.stop(0.60)
        return {
            'segment': 'straight_{}'.format(index),
            'duration_sec': round(time.time() - started, 3),
            'distance_m': round(distance, 3),
        }

    def turn_left(self, index):
        target = math.pi / 2.0
        previous_yaw = self.odom[2]
        accumulated = 0.0
        started = time.time()
        deadline = time.monotonic() + 7.0
        while time.monotonic() < deadline:
            self._require_ready()
            command = Twist()
            command.angular.z = ANGULAR_SPEED
            self.manual.publish(command)
            rclpy.spin_once(self, timeout_sec=0.02)
            current_yaw = self.odom[2]
            delta = math.atan2(
                math.sin(current_yaw - previous_yaw),
                math.cos(current_yaw - previous_yaw))
            if delta > -0.05:
                accumulated += max(0.0, delta)
            previous_yaw = current_yaw
            if accumulated >= target - 0.03:
                break
            time.sleep(0.02)
        else:
            raise RuntimeError('turn {} timed out'.format(index))
        self.stop(0.60)
        return {
            'segment': 'turn_{}'.format(index),
            'duration_sec': round(time.time() - started, 3),
            'yaw_rad': round(accumulated, 3),
        }

    def stop(self, duration_sec):
        deadline = time.monotonic() + float(duration_sec)
        while time.monotonic() < deadline:
            self.manual.publish(Twist())
            rclpy.spin_once(self, timeout_sec=0.02)
            time.sleep(0.02)

    def spin_for(self, duration_sec):
        deadline = time.monotonic() + float(duration_sec)
        while time.monotonic() < deadline:
            rclpy.spin_once(self, timeout_sec=0.05)

    def summary(self, legs):
        map_info = self.map_info or ('', 0.0, 0, 0)
        return {
            'schema': 'MappingSquareProbe/v1',
            'approval': 'area clear; operator at emergency stop',
            'limits': {
                'linear_mps': LINEAR_SPEED,
                'angular_rps': ANGULAR_SPEED,
            },
            'requested_side_m': self.side_meters,
            'segments': legs,
            'map': {
                'frame': map_info[0],
                'resolution_m': map_info[1],
                'width': map_info[2],
                'height': map_info[3],
            },
            'nonzero_cmd_vel_samples': self.nonzero_output_count,
            'final_cmd_vel_zero': self._output_is_zero(),
            'final_safety_state': self.safety_state,
            'passed': (
                self.nonzero_output_count > 0
                and self._output_is_zero()
                and self.safety_state == 'READY'),
        }

    def _require_ready(self):
        if self.safety_state != 'READY':
            raise RuntimeError(
                'safety state changed to {!r}'.format(self.safety_state))

    def _output_is_zero(self):
        return self.output is not None and all(
            abs(value) <= 1e-4 for value in self.output)

    def _safety_callback(self, message):
        self.safety_state = message.data

    def _odom_callback(self, message):
        pose = message.pose.pose
        q = pose.orientation
        yaw = math.atan2(
            2.0 * (q.w * q.z + q.x * q.y),
            1.0 - 2.0 * (q.y * q.y + q.z * q.z))
        self.odom = (pose.position.x, pose.position.y, yaw)

    def _map_callback(self, message):
        self.map_info = (
            message.header.frame_id,
            float(message.info.resolution),
            int(message.info.width),
            int(message.info.height),
        )

    def _output_callback(self, message):
        self.output = (
            float(message.linear.x),
            float(message.linear.y),
            float(message.angular.z),
        )
        if not self._output_is_zero():
            self.nonzero_output_count += 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--approval-token', required=True)
    parser.add_argument('--side-meters', type=float, default=0.50)
    args = parser.parse_args()
    if args.approval_token != APPROVAL_TOKEN:
        parser.error('explicit area-clear/e-stop approval token is required')
    if not 0.30 <= args.side_meters <= 0.80:
        parser.error('side-meters must be within 0.30..0.80')

    rclpy.init()
    node = MappingSquareProbe(args.side_meters)
    result = None
    try:
        node.wait_ready()
        legs = node.drive_square()
        result = node.summary(legs)
        if not result['passed']:
            raise RuntimeError('mapping square did not end in READY/zero')
    except Exception as exc:
        node.stop(0.80)
        result = node.summary([])
        result['error'] = '{}: {}'.format(type(exc).__name__, exc)
        result['passed'] = False
    finally:
        node.stop(0.80)
        print(json.dumps(result, indent=2, sort_keys=True), flush=True)
        node.destroy_node()
        rclpy.shutdown()
    raise SystemExit(0 if result['passed'] else 2)


if __name__ == '__main__':
    main()
