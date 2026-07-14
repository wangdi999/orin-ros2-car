#!/usr/bin/env python3
"""Observe a safety-state transition without exposing any ROS output API."""

import argparse
import json
import math
import os
import time

from geometry_msgs.msg import Twist
import rclpy
from rclpy.node import Node
from std_msgs.msg import String


def main():
    """Wait for a requested state and fail if final velocity is ever non-zero."""
    arguments = _parse_arguments()
    rclpy.init()
    node = Node('read_only_safety_state_probe')

    states = []
    command_count = 0
    nonzero_command_count = 0

    def state_callback(message):
        states.append((time.time(), message.data))

    def command_callback(message):
        nonlocal command_count, nonzero_command_count
        command_count += 1
        values = (
            message.linear.x,
            message.linear.y,
            message.angular.z,
        )
        if not all(
                math.isfinite(value) and abs(value) <= 1e-9
                for value in values):
            nonzero_command_count += 1

    subscriptions = [
        node.create_subscription(
            String, '/safety/state', state_callback, 20),
        node.create_subscription(
            Twist, '/cmd_vel', command_callback, 50),
    ]

    initial_ready = not arguments.require_initial_ready
    initial_deadline = time.monotonic() + arguments.initial_timeout_sec
    while not initial_ready and time.monotonic() < initial_deadline:
        rclpy.spin_once(node, timeout_sec=0.02)
        initial_ready = any(value == 'READY' for _, value in states)

    if arguments.require_initial_ready and not initial_ready:
        _finish(node, {
            'schema': 'ReadOnlySafetyStateProbe/v1',
            'passed': False,
            'reason': 'initial READY state was not observed',
            'states': _state_values(states),
            'cmd_vel_sample_count': command_count,
            'nonzero_cmd_vel_count': nonzero_command_count,
        }, 2)

    if arguments.trigger_file:
        print('READY_FOR_FAULT', flush=True)

    trigger_epoch = None
    expected_epoch = None
    deadline = time.monotonic() + arguments.timeout_sec
    while time.monotonic() < deadline:
        rclpy.spin_once(node, timeout_sec=0.02)
        if arguments.trigger_file and trigger_epoch is None:
            trigger_epoch = _read_trigger_epoch(arguments.trigger_file)
        if trigger_epoch is None and not arguments.trigger_file:
            trigger_epoch = time.time()
        for observed_at, value in states:
            if (value == arguments.expected_state
                    and observed_at + 1e-9 >= trigger_epoch):
                expected_epoch = observed_at
                break
        # DDS may deliver the state publisher before the velocity publisher.
        # Keep waiting until both the requested state and at least one output
        # sample have been observed so a restore cannot pass on state alone.
        if expected_epoch is not None and command_count > 0:
            break

    if expected_epoch is not None:
        _spin_for(node, arguments.settle_sec)

    latency = (
        expected_epoch - trigger_epoch
        if expected_epoch is not None and trigger_epoch is not None
        else None)
    passed = all((
        initial_ready,
        trigger_epoch is not None,
        expected_epoch is not None,
        command_count > 0,
        nonzero_command_count == 0,
    ))
    result = {
        'schema': 'ReadOnlySafetyStateProbe/v1',
        'passed': passed,
        'expected_state': arguments.expected_state,
        'expected_state_seen': expected_epoch is not None,
        'transition_latency_sec': (
            round(latency, 3) if latency is not None else None),
        'states': _state_values(states),
        'cmd_vel_sample_count': command_count,
        'nonzero_cmd_vel_count': nonzero_command_count,
        'read_only': True,
    }
    _finish(node, result, 0 if passed else 2)


def _parse_arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument('--expected-state', required=True)
    parser.add_argument('--trigger-file', default='')
    parser.add_argument('--require-initial-ready', action='store_true')
    parser.add_argument('--initial-timeout-sec', type=float, default=3.0)
    parser.add_argument('--timeout-sec', type=float, default=5.0)
    parser.add_argument('--settle-sec', type=float, default=0.50)
    result = parser.parse_args()
    if result.initial_timeout_sec <= 0 or result.timeout_sec <= 0:
        parser.error('timeouts must be positive')
    if result.settle_sec < 0:
        parser.error('settle time must be non-negative')
    return result


def _read_trigger_epoch(path):
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, 'r', encoding='ascii') as stream:
            value = float(stream.read().strip())
        return value if math.isfinite(value) else None
    except (OSError, TypeError, ValueError):
        return None


def _spin_for(node, duration_sec):
    deadline = time.monotonic() + duration_sec
    while time.monotonic() < deadline:
        rclpy.spin_once(node, timeout_sec=0.02)


def _state_values(events):
    result = []
    for _, value in events:
        if not result or result[-1] != value:
            result.append(value)
    return result


def _finish(node, result, exit_code):
    print(json.dumps(result, indent=2, sort_keys=True), flush=True)
    node.destroy_node()
    rclpy.shutdown()
    raise SystemExit(exit_code)


if __name__ == '__main__':
    main()
