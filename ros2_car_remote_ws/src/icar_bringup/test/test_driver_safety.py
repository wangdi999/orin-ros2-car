"""Unit tests for driver hard limits, watchdog and reconnect policy."""

import math
from pathlib import Path
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from icar_bringup.driver_safety import (  # noqa: E402
    DriverSafety,
    ReconnectBackoff,
    SafeMotion,
    exclusive_publisher_matches,
    serial_endpoint_is_healthy,
)


class PublisherInfo:
    """Small stand-in for rclpy TopicEndpointInfo."""

    def __init__(self, node_name):
        self.node_name = node_name


class TestDriverSafety(unittest.TestCase):
    """Verify the safety logic without importing ROS or hardware libraries."""

    def test_rejects_nan_infinity_and_non_numeric_values(self):
        safety = DriverSafety()
        for value in (math.nan, math.inf, -math.inf, 'bad', None):
            with self.subTest(value=value):
                self.assertIsNone(safety.sanitize(value, 0.0, 0.0))

    def test_hard_limits_cannot_be_configured_above_constitution(self):
        safety = DriverSafety(x_limit=10.0, y_limit=9.0, angular_limit=8.0)
        self.assertEqual(
            safety.sanitize(2.0, -2.0, 5.0),
            SafeMotion(0.35, -0.35, 0.80))

    def test_lower_runtime_limits_are_respected(self):
        safety = DriverSafety(x_limit=0.1, y_limit=0.2, angular_limit=0.4)
        self.assertEqual(
            safety.sanitize(0.2, -0.3, 0.8),
            SafeMotion(0.1, -0.2, 0.4))

    def test_watchdog_emits_one_zero_at_three_hundred_ms(self):
        safety = DriverSafety(command_timeout_sec=9.0)
        self.assertEqual(safety.command_timeout_sec, 0.30)
        safety.record_valid_command(1.0)
        self.assertFalse(safety.watchdog_zero_due(1.299))
        self.assertTrue(safety.watchdog_zero_due(1.300))
        self.assertFalse(safety.watchdog_zero_due(2.0))
        safety.record_valid_command(2.1)
        self.assertTrue(safety.watchdog_zero_due(2.4))

    def test_backward_clock_is_fail_closed(self):
        safety = DriverSafety()
        safety.record_valid_command(10.0)
        self.assertTrue(safety.watchdog_zero_due(9.0))

    def test_reconnect_attempts_are_spaced_five_seconds(self):
        backoff = ReconnectBackoff(interval_sec=5.0)
        self.assertTrue(backoff.retry_due(0.0))
        backoff.record_attempt(0.0)
        self.assertFalse(backoff.retry_due(4.999))
        self.assertTrue(backoff.retry_due(5.0))
        backoff.mark_connected()
        self.assertFalse(backoff.retry_due(100.0))
        backoff.mark_disconnected(100.0)
        self.assertFalse(backoff.retry_due(104.9))
        self.assertTrue(backoff.retry_due(105.0))

    def test_only_expected_arbiter_publisher_is_accepted(self):
        self.assertTrue(exclusive_publisher_matches(
            [PublisherInfo('cmd_vel_arbiter')], 'cmd_vel_arbiter'))
        self.assertFalse(exclusive_publisher_matches([], 'cmd_vel_arbiter'))
        self.assertFalse(exclusive_publisher_matches([
            PublisherInfo('cmd_vel_arbiter'), PublisherInfo('rosbridge')
        ], 'cmd_vel_arbiter'))
        self.assertFalse(exclusive_publisher_matches(
            [PublisherInfo('rosbridge')], 'cmd_vel_arbiter'))

    def test_serial_hangup_is_detected_even_while_port_reports_open(self):
        class Port:
            is_open = True

            @staticmethod
            def fileno():
                return 7

        class Poller:
            def __init__(self, events):
                self.events = events

            def register(self, _descriptor, _mask):
                pass

            def poll(self, _timeout):
                return self.events

        self.assertTrue(serial_endpoint_is_healthy(
            Port(), poll_factory=lambda: Poller([])))
        self.assertFalse(serial_endpoint_is_healthy(
            Port(), poll_factory=lambda: Poller([(7, 0x10)])))

    def test_invalid_serial_descriptor_fails_closed(self):
        class BrokenPort:
            is_open = True

            @staticmethod
            def fileno():
                raise OSError('device removed')

        self.assertFalse(serial_endpoint_is_healthy(BrokenPort()))
        self.assertFalse(serial_endpoint_is_healthy(None))


if __name__ == '__main__':
    unittest.main()
