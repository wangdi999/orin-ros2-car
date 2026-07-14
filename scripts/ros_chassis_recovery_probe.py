#!/usr/bin/env python3
"""Read-only proof that the chassis reconnected while output stayed zero."""

import argparse
import json
import math
import time

from geometry_msgs.msg import Twist
import rclpy
from rclpy.node import Node
from std_msgs.msg import Bool


def main():
    """Wait for a connected heartbeat and reject every non-zero output."""
    parser = argparse.ArgumentParser()
    parser.add_argument('--timeout-sec', type=float, default=16.0)
    arguments = parser.parse_args()
    if arguments.timeout_sec <= 0.0:
        parser.error('timeout must be positive')

    rclpy.init()
    node = Node('read_only_chassis_recovery_probe')
    connected_samples = []
    command_samples = []

    def connected_callback(message):
        connected_samples.append(bool(message.data))

    def command_callback(message):
        command_samples.append((
            float(message.linear.x),
            float(message.linear.y),
            float(message.angular.z),
        ))

    subscriptions = [
        node.create_subscription(
            Bool, '/chassis/connected', connected_callback, 50),
        node.create_subscription(
            Twist, '/cmd_vel', command_callback, 50),
    ]
    deadline = time.monotonic() + arguments.timeout_sec
    while time.monotonic() < deadline:
        rclpy.spin_once(node, timeout_sec=0.02)
        if (connected_samples and connected_samples[-1]
                and len(command_samples) >= 10):
            break

    nonzero = sum(
        1 for sample in command_samples
        if not all(math.isfinite(value) and abs(value) <= 1e-9
                   for value in sample))
    passed = all((
        bool(connected_samples),
        connected_samples[-1] if connected_samples else False,
        len(command_samples) >= 10,
        nonzero == 0,
    ))
    print(json.dumps({
        'schema': 'ReadOnlyChassisRecoveryProbe/v1',
        'passed': passed,
        'read_only': True,
        'connected_sample_count': len(connected_samples),
        'final_connected': (
            connected_samples[-1] if connected_samples else None),
        'cmd_vel_sample_count': len(command_samples),
        'nonzero_cmd_vel_count': nonzero,
    }, indent=2, sort_keys=True), flush=True)
    node.destroy_node()
    rclpy.shutdown()
    raise SystemExit(0 if passed else 2)


if __name__ == '__main__':
    main()
