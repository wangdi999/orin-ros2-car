"""Tests for patrol, retries, cancellation and Foxy action statuses."""

import unittest

from icar_navigation.patrol_policy import (
    ARRIVED,
    IDLE,
    NAVIGATING,
    NEXT_GOAL,
    RETURN_HOME,
    STATUS_ABORTED,
    STATUS_CANCELED,
    STATUS_SUCCEEDED,
    WAITING,
    PatrolPolicy,
)
from icar_navigation.route_loader import parse_route


def route(*, failure_policy='skip', loop=False):
    """Return a small executable route for state-machine tests."""
    return parse_route({
        'configured': True,
        'frame_id': 'map',
        'home': {'name': 'home', 'x': 0.0, 'y': 0.0, 'yaw': 0.0},
        'waypoints': [
            {'name': 'point_a', 'x': 1.0, 'y': 0.0, 'yaw': 0.0},
            {'name': 'point_b', 'x': 1.0, 'y': 1.0, 'yaw': 1.0},
            {'name': 'point_c', 'x': 0.0, 'y': 1.0, 'yaw': 3.0},
        ],
        'default_dwell_sec': 3.0,
        'max_retries': 1,
        'failure_policy': failure_policy,
        'loop': loop,
    })


class TestPatrolPolicy(unittest.TestCase):
    """Verify the independent patrol and return-home transitions."""

    def test_complete_three_point_non_loop_route(self):
        policy = PatrolPolicy()
        self.assertTrue(policy.start_patrol(route()).send_goal)
        for index in range(3):
            self.assertEqual(policy.state, NAVIGATING)
            expected = 'point_{}'.format('abc'[index])
            self.assertEqual(policy.current_waypoint.name, expected)
            result = policy.handle_goal_result(STATUS_SUCCEEDED)
            self.assertEqual(result.event, 'goal-arrived')
            self.assertEqual(policy.state, ARRIVED)
            policy.begin_waiting()
            self.assertEqual(policy.state, WAITING)
            transition = policy.dwell_elapsed()
            if index < 2:
                self.assertTrue(transition.send_goal)
            else:
                self.assertTrue(transition.terminal)
        self.assertEqual(policy.state, IDLE)
        self.assertEqual(policy.reason, 'route_completed')

    def test_unreachable_point_retries_once_then_skips(self):
        policy = PatrolPolicy()
        policy.start_patrol(route())
        retry = policy.handle_goal_result(STATUS_ABORTED)
        self.assertEqual(retry.event, 'goal-retry')
        self.assertTrue(retry.send_goal)
        self.assertEqual(policy.attempt, 1)
        skipped = policy.handle_goal_result(STATUS_ABORTED)
        self.assertEqual(skipped.event, 'waypoint-skipped')
        self.assertTrue(skipped.publish_alarm)
        self.assertEqual(policy.state, NEXT_GOAL)
        self.assertTrue(policy.advance_after_next_goal().send_goal)
        self.assertEqual(policy.current_waypoint.name, 'point_b')

    def test_abort_policy_stops_after_retry_exhausted(self):
        policy = PatrolPolicy()
        policy.start_patrol(route(failure_policy='abort'))
        policy.handle_goal_result(STATUS_ABORTED)
        result = policy.handle_goal_result(STATUS_ABORTED)
        self.assertEqual(result.event, 'route-aborted')
        self.assertTrue(result.terminal)
        self.assertEqual(policy.state, IDLE)

    def test_cancel_never_resumes_previous_route(self):
        policy = PatrolPolicy()
        policy.start_patrol(route())
        self.assertEqual(
            policy.cancel('manual_takeover').event, 'cancel-requested')
        policy.cancellation_complete()
        self.assertEqual(policy.state, IDLE)
        self.assertEqual(policy.reason, 'manual_takeover')

    def test_canceled_rejected_and_timeout_are_status_driven(self):
        policy = PatrolPolicy()
        policy.start_patrol(route())
        self.assertEqual(
            policy.handle_goal_result(STATUS_CANCELED).event,
            'goal-canceled')

        policy.start_patrol(route())
        self.assertEqual(
            policy.handle_goal_result(0, rejected=True).event,
            'goal-retry')

        policy = PatrolPolicy()
        policy.start_patrol(route())
        self.assertEqual(
            policy.handle_goal_result(0, timed_out=True).event,
            'goal-retry')

    def test_timeout_retries_only_after_remote_goal_is_terminal(self):
        policy = PatrolPolicy()
        policy.start_patrol(route())
        policy.cancel('goal_timeout')
        transition = policy.timeout_cancellation_complete(STATUS_CANCELED)
        self.assertEqual(transition.event, 'goal-retry')
        self.assertTrue(transition.send_goal)
        self.assertEqual(policy.attempt, 1)

    def test_goal_success_wins_a_timeout_cancel_race(self):
        policy = PatrolPolicy()
        policy.start_patrol(route())
        policy.cancel('goal_timeout')
        transition = policy.timeout_cancellation_complete(STATUS_SUCCEEDED)
        self.assertEqual(transition.event, 'goal-arrived')
        self.assertEqual(policy.state, ARRIVED)

    def test_return_home_success_reports_home_reached(self):
        policy = PatrolPolicy()
        policy.start_return_home(route())
        self.assertEqual(policy.mode, RETURN_HOME)
        self.assertEqual(policy.current_waypoint.name, 'home')
        result = policy.handle_goal_result(STATUS_SUCCEEDED)
        self.assertEqual(result.event, 'home-reached')
        self.assertEqual(policy.state, IDLE)
        self.assertEqual(policy.status_dict()['reason'], 'home_reached')
        self.assertTrue(policy.status_dict()['route_configured'])

    def test_return_home_retries_once_then_latches_failure(self):
        policy = PatrolPolicy()
        policy.start_return_home(route())
        self.assertEqual(
            policy.handle_goal_result(STATUS_ABORTED).event,
            'goal-retry')
        result = policy.handle_goal_result(STATUS_ABORTED)
        self.assertEqual(result.event, 'return-failed')
        self.assertTrue(result.terminal)
        self.assertEqual(policy.state, IDLE)
        self.assertEqual(policy.status_dict()['reason'], 'return_failed')

    def test_low_battery_return_never_resumes_the_interrupted_patrol(self):
        policy = PatrolPolicy()
        policy.start_patrol(route())
        self.assertEqual(policy.current_waypoint.name, 'point_a')
        policy.cancel('low_battery')
        policy.cancellation_complete()
        policy.start_return_home(route())
        self.assertEqual(policy.current_waypoint.name, 'home')
        policy.handle_goal_result(STATUS_SUCCEEDED)
        self.assertEqual(policy.state, IDLE)
        self.assertEqual(policy.reason, 'home_reached')
        self.assertEqual(policy.mode, RETURN_HOME)

        failed = PatrolPolicy()
        failed.start_patrol(route())
        failed.cancel('low_battery')
        failed.cancellation_complete()
        failed.start_return_home(route())
        failed.handle_goal_result(STATUS_ABORTED)
        failed.handle_goal_result(STATUS_ABORTED)
        self.assertEqual(failed.state, IDLE)
        self.assertEqual(failed.reason, 'return_failed')
        self.assertEqual(failed.mode, RETURN_HOME)

    def test_missing_route_can_report_fail_closed_return_result(self):
        policy = PatrolPolicy()
        result = policy.fail_return_home('route-not-configured')
        self.assertTrue(result.terminal)
        self.assertTrue(result.publish_alarm)
        self.assertEqual(policy.mode, RETURN_HOME)
        self.assertEqual(policy.status_dict()['reason'], 'return_failed')


if __name__ == '__main__':
    unittest.main()
