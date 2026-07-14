#!/usr/bin/env python3
"""Exercise only zero-command timeout and e-stop/reset safety paths."""

import json
import math
import time

from geometry_msgs.msg import Twist
import rclpy
from rclpy.node import Node
from std_msgs.msg import Bool, String
from std_srvs.srv import Trigger


def main():
    """Publish only zero Twist/e-stop controls and fail on non-zero output."""
    rclpy.init()
    node = Node('zero_only_fault_probe')
    manual_publisher = node.create_publisher(
        Twist, '/cmd_vel_manual', 10)
    estop_publisher = node.create_publisher(
        Bool, '/safety/estop', 10)
    reset_client = node.create_client(Trigger, '/safety/reset')

    output_count = 0
    nonzero_output_count = 0
    source_events = []
    safety_events = []

    def output_callback(message):
        nonlocal output_count, nonzero_output_count
        output_count += 1
        values = (
            message.linear.x,
            message.linear.y,
            message.angular.z,
        )
        if not all(
                math.isfinite(value) and abs(value) <= 1e-9
                for value in values):
            nonzero_output_count += 1

    def source_callback(message):
        source_events.append((time.monotonic(), message.data))

    def safety_callback(message):
        safety_events.append((time.monotonic(), message.data))

    subscriptions = [
        node.create_subscription(
            Twist, '/cmd_vel', output_callback, 50),
        node.create_subscription(
            String, '/control/active_source', source_callback, 20),
        node.create_subscription(
            String, '/safety/state', safety_callback, 20),
    ]

    _spin_for(node, 1.0)
    if not safety_events or safety_events[-1][1] != 'READY':
        raise RuntimeError('safe-base must be READY before zero-only probe')

    source_events.clear()
    manual_started_at = time.monotonic()
    while time.monotonic() - manual_started_at < 0.40:
        manual_publisher.publish(Twist())
        rclpy.spin_once(node, timeout_sec=0.01)
        time.sleep(0.04)
    manual_stopped_at = time.monotonic()
    _spin_for(node, 1.0)

    manual_seen = any(value == 'MANUAL' for _, value in source_events)
    none_events = [timestamp for timestamp, value in source_events
                   if value == 'NONE' and timestamp >= manual_stopped_at]
    timeout_latency_sec = (
        none_events[0] - manual_stopped_at if none_events else None)

    safety_events.clear()
    _publish_bool(node, estop_publisher, True, 0.20)
    _spin_for(node, 0.50)
    estop_seen = any(value == 'ESTOP' for _, value in safety_events)

    _publish_bool(node, estop_publisher, False, 0.20)
    _spin_for(node, 0.35)
    latched_after_release = (
        bool(safety_events) and safety_events[-1][1] == 'ESTOP')

    if not reset_client.wait_for_service(timeout_sec=2.0):
        raise RuntimeError('/safety/reset is unavailable')
    future = reset_client.call_async(Trigger.Request())
    deadline = time.monotonic() + 2.0
    while not future.done() and time.monotonic() < deadline:
        rclpy.spin_once(node, timeout_sec=0.05)
    if not future.done():
        raise RuntimeError('/safety/reset timed out')
    response = future.result()
    _spin_for(node, 0.40)
    ready_after_reset = (
        bool(safety_events) and safety_events[-1][1] == 'READY')

    result = {
        'schema': 'ZeroOnlyFaultProbe/v1',
        'manual_started': manual_seen,
        'command_timeout_to_none_sec': (
            round(timeout_latency_sec, 3)
            if timeout_latency_sec is not None else None),
        'estop_seen': estop_seen,
        'estop_latched_after_release': latched_after_release,
        'reset_success': bool(response and response.success),
        'reset_message': response.message if response else None,
        'ready_after_reset': ready_after_reset,
        'cmd_vel_sample_count': output_count,
        'nonzero_cmd_vel_count': nonzero_output_count,
    }
    print(json.dumps(result, indent=2, sort_keys=True))

    passed = all((
        manual_seen,
        timeout_latency_sec is not None,
        timeout_latency_sec <= 0.40,
        estop_seen,
        latched_after_release,
        bool(response and response.success),
        ready_after_reset,
        output_count > 0,
        nonzero_output_count == 0,
    ))
    node.destroy_node()
    rclpy.shutdown()
    raise SystemExit(0 if passed else 2)


def _spin_for(node, duration_sec):
    deadline = time.monotonic() + duration_sec
    while time.monotonic() < deadline:
        rclpy.spin_once(node, timeout_sec=0.02)


def _publish_bool(node, publisher, value, duration_sec):
    deadline = time.monotonic() + duration_sec
    while time.monotonic() < deadline:
        publisher.publish(Bool(data=value))
        rclpy.spin_once(node, timeout_sec=0.01)
        time.sleep(0.04)


if __name__ == '__main__':
    main()
