"""Tests for strict, non-executable route drafts."""

import copy
import math
import unittest

from icar_navigation.route_loader import (
    RouteValidationError,
    parse_route,
    require_executable_route,
    route_path_points,
)


def draft_route():
    """Return the safe null-coordinate repository template."""
    return {
        'configured': False,
        'frame_id': 'map',
        'home': {'name': 'home', 'x': None, 'y': None, 'yaw': None},
        'waypoints': [
            {'name': 'point_a', 'x': None, 'y': None, 'yaw': None},
            {'name': 'point_b', 'x': None, 'y': None, 'yaw': None},
            {'name': 'point_c', 'x': None, 'y': None, 'yaw': None},
        ],
        'default_dwell_sec': 3.0,
        'max_retries': 1,
        'failure_policy': 'skip',
        'loop': False,
    }


def executable_route():
    """Return a complete measured-coordinate route."""
    data = draft_route()
    data['configured'] = True
    for index, point in enumerate([data['home']] + data['waypoints']):
        point.update(x=float(index), y=0.1 * index, yaw=0.0)
    return data


class TestRouteLoader(unittest.TestCase):
    """Verify safe draft and executable route validation."""

    def test_null_coordinate_draft_parses_but_cannot_execute(self):
        route = parse_route(draft_route())
        self.assertFalse(route.configured)
        with self.assertRaisesRegex(RouteValidationError, 'not configured'):
            require_executable_route(route)

    def test_configured_route_requires_finite_coordinates(self):
        data = draft_route()
        data['configured'] = True
        with self.assertRaisesRegex(RouteValidationError, 'must be numeric'):
            parse_route(data)

        data = executable_route()
        data['waypoints'][0]['x'] = math.inf
        with self.assertRaisesRegex(RouteValidationError, 'must be finite'):
            parse_route(data)

    def test_executable_route_has_home_three_points_and_defaults(self):
        route = require_executable_route(parse_route(executable_route()))
        self.assertEqual(route.frame_id, 'map')
        self.assertEqual(route.home.name, 'home')
        self.assertEqual(len(route.waypoints), 3)
        self.assertEqual(route.default_dwell_sec, 3.0)
        self.assertEqual(route.max_retries, 1)
        self.assertEqual(route.failure_policy, 'skip')
        self.assertFalse(route.loop)

    def test_missing_extra_and_invalid_root_fields_are_rejected(self):
        mutations = [
            lambda data: data.pop('home'),
            lambda data: data.update(extra='bad'),
            lambda data: data.update(frame_id='odom'),
            lambda data: data.update(waypoints=data['waypoints'][:2]),
            lambda data: data.update(max_retries=4),
            lambda data: data.update(failure_policy='continue'),
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                data = executable_route()
                mutation(data)
                with self.assertRaises(RouteValidationError):
                    parse_route(data)

    def test_duplicate_names_and_out_of_range_yaw_are_rejected(self):
        data = executable_route()
        data['waypoints'][0]['name'] = 'home'
        with self.assertRaisesRegex(RouteValidationError, 'unique'):
            parse_route(data)

        data = executable_route()
        data['waypoints'][0]['yaw'] = math.pi + 0.01
        with self.assertRaisesRegex(RouteValidationError, 'yaw'):
            parse_route(data)

    def test_extra_field_and_negative_dwell_are_rejected(self):
        data = executable_route()
        data['waypoints'][0]['unknown'] = 1
        with self.assertRaisesRegex(RouteValidationError, 'fields invalid'):
            parse_route(data)

        data = executable_route()
        data['waypoints'][0]['dwell_sec'] = -1
        with self.assertRaisesRegex(RouteValidationError, 'non-negative'):
            parse_route(data)

    def test_input_is_not_mutated(self):
        data = executable_route()
        original = copy.deepcopy(data)
        parse_route(data)
        self.assertEqual(data, original)

    def test_route_path_is_empty_for_draft_and_contains_home_plus_waypoints(self):
        draft = parse_route(draft_route())
        configured = parse_route(executable_route())

        self.assertEqual(route_path_points(draft), ())
        points = route_path_points(configured)
        self.assertEqual(len(points), 4)
        for actual, expected in zip(points, (
                (0.0, 0.0, 0.0),
                (1.0, 0.1, 0.0),
                (2.0, 0.2, 0.0),
                (3.0, 0.3, 0.0))):
            for actual_value, expected_value in zip(actual, expected):
                self.assertAlmostEqual(actual_value, expected_value)


if __name__ == '__main__':
    unittest.main()
