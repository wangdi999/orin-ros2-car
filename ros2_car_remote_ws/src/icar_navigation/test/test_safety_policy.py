"""Tests for safety latching and low-battery hysteresis."""

import unittest

from icar_navigation.safety_policy import (
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


def healthy(**overrides):
    """Return a fully healthy snapshot with optional field overrides."""
    values = {
        'chassis_connected': True,
        'chassis_age_sec': 0.05,
        'scan_age_sec': 0.10,
        'odom_age_sec': 0.05,
        'tf_complete': True,
        'ownership_valid': True,
    }
    values.update(overrides)
    return HealthSnapshot(**values)


def ready_policy(test_case):
    """Create a policy whose startup gate has passed."""
    policy = SafetyPolicy(started_at=0.0)
    test_case.assertEqual(policy.evaluate(healthy(), 5.0), READY)
    return policy


class TestSafetyPolicy(unittest.TestCase):
    """Verify health latches, reset gates and battery behavior."""

    def test_startup_is_fail_closed_until_grace_and_health_pass(self):
        policy = SafetyPolicy(started_at=10.0)
        self.assertEqual(policy.evaluate(
            healthy(ownership_valid=False), 14.9), INITIALIZING)
        self.assertEqual(policy.evaluate(healthy(), 15.0), READY)

    def test_estop_is_immediate_during_startup_grace(self):
        policy = SafetyPolicy(started_at=10.0)
        policy.set_estop(True)
        self.assertEqual(policy.evaluate(healthy(), 10.1), ESTOP)

    def test_each_health_failure_latches_expected_state(self):
        cases = [
            (healthy(ownership_valid=False), OWNERSHIP_FAULT),
            (healthy(chassis_connected=False), CHASSIS_FAULT),
            (healthy(chassis_age_sec=0.31), CHASSIS_FAULT),
            (healthy(scan_age_sec=0.41), SENSOR_FAULT),
            (healthy(odom_age_sec=0.21), ODOM_TF_FAULT),
            (healthy(tf_complete=False), ODOM_TF_FAULT),
        ]
        for snapshot, expected in cases:
            with self.subTest(expected=expected, snapshot=snapshot):
                policy = ready_policy(self)
                self.assertEqual(policy.evaluate(snapshot, 5.1), expected)
                self.assertEqual(policy.evaluate(healthy(), 5.2), expected)

    def test_reset_requires_fault_clear_zero_output_and_no_action(self):
        policy = ready_policy(self)
        self.assertEqual(
            policy.evaluate(healthy(scan_age_sec=1.0), 5.1), SENSOR_FAULT)
        self.assertFalse(policy.reset(healthy(scan_age_sec=1.0), 5.2)[0])
        self.assertFalse(policy.reset(healthy(), 5.2, action_active=True)[0])
        self.assertFalse(policy.reset(
            healthy(), 5.2, output_is_zero=False)[0])
        success, _ = policy.reset(healthy(), 5.2)
        self.assertTrue(success)
        self.assertEqual(policy.state, READY)

    def test_estop_false_does_not_clear_latch_without_reset(self):
        policy = ready_policy(self)
        policy.set_estop(True)
        self.assertEqual(policy.state, ESTOP)
        policy.set_estop(False)
        self.assertEqual(policy.evaluate(healthy(), 5.1), ESTOP)
        self.assertTrue(policy.reset(healthy(), 5.2)[0])

    def test_low_battery_return_has_explicit_terminal_latches(self):
        policy = ready_policy(self)
        self.assertTrue(policy.request_low_battery_return(healthy(), 5.1)[0])
        self.assertEqual(policy.state, LOW_BATTERY_RETURN)
        self.assertFalse(policy.reset(healthy(), 5.2)[0])
        self.assertTrue(policy.report_return_result(True))
        self.assertEqual(policy.state, RETURNED_HOME)
        self.assertTrue(policy.reset(healthy(), 5.3)[0])

        self.assertTrue(policy.request_low_battery_return(healthy(), 5.4)[0])
        self.assertTrue(policy.report_return_result(False))
        self.assertEqual(policy.state, RETURN_FAILED)

    def test_real_low_battery_disabled_despite_sustained_low_samples(self):
        monitor = BatteryMonitor()
        for index in range(20):
            self.assertFalse(
                monitor.add_sample(10.5, float(index), enabled=False))
        self.assertFalse(monitor.triggered)

    def test_low_battery_requires_window_sustain_then_recovers(self):
        monitor = BatteryMonitor()
        for index in range(10):
            self.assertFalse(
                monitor.add_sample(10.5, float(index), enabled=True))
        self.assertEqual(monitor.average, 10.5)
        self.assertFalse(monitor.add_sample(10.5, 13.9, enabled=True))
        self.assertTrue(monitor.add_sample(10.5, 14.0, enabled=True))
        self.assertTrue(monitor.triggered)

        for index in range(10):
            monitor.add_sample(11.3, 15.0 + index, enabled=True)
        self.assertGreater(monitor.average, 11.1)
        self.assertFalse(monitor.triggered)

    def test_non_finite_voltage_is_ignored(self):
        monitor = BatteryMonitor()
        self.assertFalse(monitor.add_sample(
            float('nan'), 0.0, enabled=True))
        self.assertIsNone(monitor.average)

    def test_low_battery_and_recovery_thresholds_are_inclusive(self):
        monitor = BatteryMonitor()
        for index in range(10):
            monitor.add_sample(10.8, float(index), enabled=True)
        self.assertTrue(monitor.add_sample(10.8, 14.0, enabled=True))
        for index in range(10):
            monitor.add_sample(11.1, 15.0 + index, enabled=True)
        self.assertAlmostEqual(monitor.average, 11.1)
        self.assertFalse(monitor.triggered)

    def test_real_low_battery_precondition_failure_locks_motion(self):
        policy = ready_policy(self)
        policy.force_return_failed('home route is not configured')
        self.assertEqual(policy.state, RETURN_FAILED)
        self.assertFalse(policy.reset(
            healthy(), 5.1, output_is_zero=False)[0])


if __name__ == '__main__':
    unittest.main()
