"""Tests for fail-closed command arbitration."""

import math
import unittest

from icar_navigation.motion_policy import (
    BLOCKED,
    LOW_BATTERY_RETURN,
    MANUAL,
    NAVIGATION,
    NONE,
    READY,
    RETURN_HOME,
    ZEROING,
    MotionPolicy,
    TwistCommand,
)


def ready_policy(now=0.0):
    """Create a policy with a fresh READY heartbeat."""
    policy = MotionPolicy()
    policy.update_chassis_state(True, now)
    policy.update_safety_state(READY, now)
    return policy


def settle_switch(test_case, policy, now):
    """Consume the mandatory zero-before-switch cycle."""
    first = policy.decide(now)
    test_case.assertEqual(first.active_source, ZEROING)
    return policy.decide(now + 0.001)


class TestMotionPolicy(unittest.TestCase):
    """Verify command priority, freshness and fail-closed behavior."""

    def test_rejects_non_finite_requests_and_fails_to_zero(self):
        policy = ready_policy()
        self.assertFalse(policy.update_manual(
            TwistCommand(math.nan, 0.0, 0.0), 0.0))
        decision = policy.decide(0.0)
        self.assertEqual(decision.active_source, NONE)
        self.assertEqual(decision.command, TwistCommand.zero())

    def test_manual_command_is_clamped_after_zero_switch_cycle(self):
        policy = ready_policy()
        self.assertTrue(policy.update_manual(
            TwistCommand(2.0, -2.0, 5.0), 0.0))
        decision = settle_switch(self, policy, 0.0)
        self.assertEqual(decision.active_source, MANUAL)
        self.assertEqual(decision.command, TwistCommand(0.50, -0.50, 2.00))

    def test_navigation_lateral_motion_is_always_zero(self):
        policy = ready_policy()
        policy.update_navigation(TwistCommand(0.05, 0.08, 0.1), 0.0)
        decision = settle_switch(self, policy, 0.0)
        self.assertEqual(decision.active_source, NAVIGATION)
        self.assertEqual(decision.command.linear_y, 0.0)

    def test_patrol_cancellation_and_dwell_block_old_navigation(self):
        for state in ('ARRIVED', 'WAITING', 'NEXT_GOAL', 'CANCELLING'):
            with self.subTest(state=state):
                policy = ready_policy()
                policy.update_patrol_status(
                    {'mode': 'PATROL', 'state': state}, 0.0)
                policy.update_navigation(
                    TwistCommand(0.05, 0.0, 0.0), 0.0)
                decision = policy.decide(0.0)
                self.assertEqual(decision.active_source, NONE)
                self.assertEqual(
                    decision.reason, 'patrol-transition-blocked')

    def test_manual_takeover_forces_zero_and_requests_cancel(self):
        policy = ready_policy()
        policy.update_navigation(TwistCommand(0.05, 0.0, 0.0), 0.0)
        self.assertEqual(
            settle_switch(self, policy, 0.0).active_source, NAVIGATION)
        policy.update_manual(TwistCommand(0.02, 0.0, 0.0), 0.01)
        switching = policy.decide(0.01)
        self.assertEqual(switching.active_source, ZEROING)
        self.assertTrue(switching.cancel_navigation)
        self.assertEqual(switching.command, TwistCommand.zero())
        self.assertEqual(policy.decide(0.011).active_source, MANUAL)

    def test_manual_takeover_never_auto_resumes_old_navigation(self):
        policy = ready_policy()
        policy.update_navigation(TwistCommand(0.05, 0.0, 0.0), 0.0)
        settle_switch(self, policy, 0.0)
        policy.update_manual(TwistCommand(0.02, 0.0, 0.0), 0.01)
        settle_switch(self, policy, 0.01)

        policy.update_chassis_state(True, 0.32)
        policy.update_safety_state(READY, 0.32)
        policy.update_navigation(TwistCommand(0.05, 0.0, 0.0), 0.32)
        decision = policy.decide(0.32)
        self.assertEqual(decision.active_source, NONE)
        self.assertEqual(decision.reason, 'navigation-inhibited')

        policy.update_patrol_status({'state': 'IDLE', 'mode': 'PATROL'}, 0.33)
        policy.update_patrol_status(
            {'state': 'NAVIGATING', 'mode': 'PATROL'}, 0.34)
        self.assertEqual(policy.decide(0.34).active_source, ZEROING)
        self.assertEqual(policy.decide(0.341).active_source, NAVIGATION)

    def test_stale_safety_heartbeat_blocks_fresh_commands(self):
        policy = ready_policy()
        policy.update_manual(TwistCommand(0.05, 0.0, 0.0), 0.29)
        policy.update_chassis_state(True, 0.301)
        decision = policy.decide(0.301)
        self.assertEqual(decision.active_source, BLOCKED)
        self.assertEqual(decision.reason, 'safety-state-stale')

    def test_stale_command_returns_to_none_and_zero(self):
        policy = ready_policy()
        policy.update_manual(TwistCommand(0.05, 0.0, 0.0), 0.0)
        settle_switch(self, policy, 0.0)
        policy.update_chassis_state(True, 0.31)
        policy.update_safety_state(READY, 0.31)
        decision = policy.decide(0.31)
        self.assertEqual(decision.active_source, NONE)
        self.assertEqual(decision.command, TwistCommand.zero())

    def test_low_battery_blocks_ordinary_manual_and_navigation(self):
        policy = MotionPolicy()
        policy.update_chassis_state(True, 0.0)
        policy.update_safety_state(LOW_BATTERY_RETURN, 0.0)
        policy.update_manual(TwistCommand(0.05, 0.0, 0.0), 0.0)
        policy.update_navigation(TwistCommand(0.05, 0.0, 0.0), 0.0)
        decision = policy.decide(0.0)
        self.assertEqual(decision.active_source, BLOCKED)
        self.assertEqual(decision.reason, 'return-home-not-authorized')

    def test_low_battery_only_allows_fresh_return_home_handshake(self):
        policy = MotionPolicy()
        policy.update_chassis_state(True, 0.0)
        policy.update_safety_state(LOW_BATTERY_RETURN, 0.0)
        policy.update_patrol_status({
            'mode': RETURN_HOME,
            'state': 'NAVIGATING',
        }, 0.0)
        policy.update_navigation(TwistCommand(0.05, 0.09, 0.1), 0.0)
        decision = settle_switch(self, policy, 0.0)
        self.assertEqual(decision.active_source, RETURN_HOME)
        self.assertEqual(decision.command.linear_y, 0.0)

        policy.update_chassis_state(True, 0.31)
        policy.update_safety_state(LOW_BATTERY_RETURN, 0.31)
        stale = policy.decide(0.31)
        self.assertEqual(stale.active_source, BLOCKED)
        self.assertEqual(stale.reason, 'return-home-not-authorized')

    def test_non_ready_state_cancels_navigation_and_blocks(self):
        policy = ready_policy()
        policy.update_navigation(TwistCommand(0.05, 0.0, 0.0), 0.0)
        settle_switch(self, policy, 0.0)
        policy.update_safety_state('ESTOP', 0.01)
        decision = policy.decide(0.01)
        self.assertEqual(decision.active_source, BLOCKED)
        self.assertTrue(decision.cancel_navigation)

    def test_missing_direct_chassis_heartbeat_fails_closed(self):
        policy = MotionPolicy()
        policy.update_safety_state(READY, 0.0)
        policy.update_manual(TwistCommand(0.05, 0.0, 0.0), 0.0)
        decision = policy.decide(0.0)
        self.assertEqual(decision.active_source, BLOCKED)
        self.assertEqual(decision.reason, 'chassis-state-stale')

    def test_disconnected_chassis_immediately_blocks_live_manual_request(self):
        policy = ready_policy()
        policy.update_manual(TwistCommand(0.05, 0.0, 0.0), 0.0)
        settle_switch(self, policy, 0.0)
        policy.update_chassis_state(False, 0.01)
        decision = policy.decide(0.01)
        self.assertEqual(decision.active_source, BLOCKED)
        self.assertEqual(decision.command, TwistCommand.zero())
        self.assertEqual(decision.reason, 'chassis-disconnected')

    def test_stale_direct_chassis_heartbeat_blocks_fresh_safety_state(self):
        policy = ready_policy()
        policy.update_manual(TwistCommand(0.05, 0.0, 0.0), 0.29)
        policy.update_safety_state(READY, 0.301)
        decision = policy.decide(0.301)
        self.assertEqual(decision.active_source, BLOCKED)
        self.assertEqual(decision.reason, 'chassis-state-stale')


if __name__ == '__main__':
    unittest.main()
