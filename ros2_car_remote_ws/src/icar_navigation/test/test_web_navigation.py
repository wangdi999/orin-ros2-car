import math
import unittest
from pathlib import Path

from icar_navigation.patrol_policy import (
    IDLE,
    NAVIGATING,
    SINGLE_GOAL,
    STATUS_ABORTED,
    STATUS_CANCELED,
    STATUS_SUCCEEDED,
    PatrolPolicy,
)
from icar_navigation.route_loader import Waypoint


ROOT = Path(__file__).resolve().parents[2]


class TestWebNavigation(unittest.TestCase):
    def test_navigate_pose_interface_is_generated_by_car_interfaces(self):
        interface = ROOT / 'car_interfaces' / 'srv' / 'NavigatePose.srv'
        self.assertTrue(interface.is_file())
        text = interface.read_text(encoding='utf-8')
        for field in ('float64 x', 'float64 y', 'float64 yaw',
                      'bool accepted', 'string goal_id', 'string message'):
            self.assertIn(field, text)

    def test_single_goal_has_one_owner_and_terminal_statuses(self):
        policy = PatrolPolicy()
        goal = Waypoint('web-goal', 1.0, -0.5, math.pi / 2.0)
        transition = policy.start_single_goal(goal, goal_id='web-1')
        self.assertTrue(transition.send_goal)
        self.assertEqual(policy.mode, SINGLE_GOAL)
        self.assertEqual(policy.state, NAVIGATING)
        self.assertEqual(policy.status_dict()['goal_id'], 'web-1')

        second = policy.start_single_goal(goal, goal_id='web-2')
        self.assertEqual(second.event, 'already-active')
        self.assertTrue(second.terminal)

        completed = policy.handle_goal_result(STATUS_SUCCEEDED)
        self.assertEqual(completed.event, 'single-goal-succeeded')
        self.assertEqual(policy.state, IDLE)
        self.assertEqual(policy.reason, 'goal_succeeded')

    def test_single_goal_abort_cancel_and_timeout_are_terminal(self):
        scenarios = [
            (STATUS_ABORTED, {}, 'goal_aborted'),
            (STATUS_CANCELED, {}, 'goal_canceled'),
            (0, {'timed_out': True}, 'goal_timeout'),
        ]
        for status, kwargs, reason in scenarios:
            with self.subTest(reason=reason):
                policy = PatrolPolicy()
                policy.start_single_goal(
                    Waypoint('web-goal', 0.1, 0.2, 0.3), goal_id=reason)
                transition = policy.handle_goal_result(status, **kwargs)
                self.assertTrue(transition.terminal)
                self.assertEqual(policy.state, IDLE)
                self.assertEqual(policy.reason, reason)


if __name__ == '__main__':
    unittest.main()
