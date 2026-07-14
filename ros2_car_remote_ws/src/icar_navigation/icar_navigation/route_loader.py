"""Strict patrol route parsing with a non-executable draft mode."""

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Optional, Tuple

import yaml


class RouteValidationError(ValueError):
    """Raised when route data cannot safely be executed."""


@dataclass(frozen=True)
class Waypoint:
    """A map-frame planar waypoint."""

    name: str
    x: Optional[float]
    y: Optional[float]
    yaw: Optional[float]
    dwell_sec: Optional[float] = None


@dataclass(frozen=True)
class RouteConfig:
    """A complete route, executable only when configured is true."""

    configured: bool
    frame_id: str
    home: Waypoint
    waypoints: Tuple[Waypoint, ...]
    default_dwell_sec: float
    max_retries: int
    failure_policy: str
    loop: bool


_ROOT_FIELDS = {
    'configured', 'frame_id', 'home', 'waypoints',
    'default_dwell_sec', 'max_retries', 'failure_policy', 'loop',
}
_WAYPOINT_FIELDS = {'name', 'x', 'y', 'yaw', 'dwell_sec'}


def load_route(path):
    """Load and validate a YAML route from disk."""
    path = Path(path)
    try:
        data = yaml.safe_load(path.read_text(encoding='utf-8'))
    except (OSError, yaml.YAMLError) as exc:
        raise RouteValidationError('unable to read route: {}'.format(exc)) from exc
    return parse_route(data)


def parse_route(data):
    """Validate parsed YAML data and return an immutable route."""
    if not isinstance(data, dict):
        raise RouteValidationError('route root must be a mapping')
    _require_exact_fields(data, _ROOT_FIELDS, 'route')

    configured = _strict_bool(data['configured'], 'configured')
    if data['frame_id'] != 'map':
        raise RouteValidationError('frame_id must be map')
    default_dwell = _nonnegative(data['default_dwell_sec'], 'default_dwell_sec')
    max_retries = data['max_retries']
    if isinstance(max_retries, bool) or not isinstance(max_retries, int):
        raise RouteValidationError('max_retries must be an integer')
    if not 0 <= max_retries <= 3:
        raise RouteValidationError('max_retries must be between 0 and 3')
    if data['failure_policy'] not in {'skip', 'abort'}:
        raise RouteValidationError('failure_policy must be skip or abort')
    loop = _strict_bool(data['loop'], 'loop')

    home = _parse_waypoint(data['home'], configured, 'home')
    raw_waypoints = data['waypoints']
    if not isinstance(raw_waypoints, list) or len(raw_waypoints) != 3:
        raise RouteValidationError('waypoints must contain exactly three entries')
    waypoints = tuple(_parse_waypoint(item, configured, 'waypoint')
                      for item in raw_waypoints)
    names = [home.name] + [waypoint.name for waypoint in waypoints]
    if len(set(names)) != len(names):
        raise RouteValidationError('home and waypoint names must be unique')

    return RouteConfig(
        configured=configured,
        frame_id='map',
        home=home,
        waypoints=waypoints,
        default_dwell_sec=default_dwell,
        max_retries=max_retries,
        failure_policy=data['failure_policy'],
        loop=loop,
    )


def require_executable_route(route):
    """Reject a draft route before any action goal can be constructed."""
    if not isinstance(route, RouteConfig) or not route.configured:
        raise RouteValidationError(
            'route is not configured; measure map coordinates first')
    for waypoint in (route.home,) + route.waypoints:
        if any(value is None for value in (waypoint.x, waypoint.y, waypoint.yaw)):
            raise RouteValidationError('configured route contains null coordinates')
    return route


def route_path_points(route):
    """Return display-only map points, or an empty tuple for an inert draft."""
    if not isinstance(route, RouteConfig) or not route.configured:
        return ()
    points = (route.home,) + route.waypoints
    if any(any(value is None for value in (point.x, point.y, point.yaw))
           for point in points):
        return ()
    return tuple((point.x, point.y, point.yaw) for point in points)


def _parse_waypoint(data, configured, label):
    if not isinstance(data, dict):
        raise RouteValidationError('{} must be a mapping'.format(label))
    required = {'name', 'x', 'y', 'yaw'}
    missing = required - set(data)
    extra = set(data) - _WAYPOINT_FIELDS
    if missing or extra:
        raise RouteValidationError(
            '{} fields invalid; missing={}, extra={}'.format(
                label, sorted(missing), sorted(extra)))
    name = data['name']
    if not isinstance(name, str) or not name.strip():
        raise RouteValidationError('{} name must be non-empty'.format(label))
    coordinates = []
    for field in ('x', 'y', 'yaw'):
        value = data[field]
        if value is None and not configured:
            coordinates.append(None)
            continue
        value = _finite_number(value, '{}.{}'.format(label, field))
        coordinates.append(value)
    if coordinates[2] is not None and not -math.pi <= coordinates[2] <= math.pi:
        raise RouteValidationError('{}.yaw must be within [-pi, pi]'.format(label))
    dwell = data.get('dwell_sec')
    if dwell is not None:
        dwell = _nonnegative(dwell, '{}.dwell_sec'.format(label))
    return Waypoint(name.strip(), *coordinates, dwell_sec=dwell)


def _require_exact_fields(data, expected, label):
    missing = expected - set(data)
    extra = set(data) - expected
    if missing or extra:
        raise RouteValidationError(
            '{} fields invalid; missing={}, extra={}'.format(
                label, sorted(missing), sorted(extra)))


def _strict_bool(value, field):
    if not isinstance(value, bool):
        raise RouteValidationError('{} must be boolean'.format(field))
    return value


def _finite_number(value, field):
    if isinstance(value, bool):
        raise RouteValidationError('{} must be numeric'.format(field))
    try:
        value = float(value)
    except (TypeError, ValueError) as exc:
        raise RouteValidationError('{} must be numeric'.format(field)) from exc
    if not math.isfinite(value):
        raise RouteValidationError('{} must be finite'.format(field))
    return value


def _nonnegative(value, field):
    value = _finite_number(value, field)
    if value < 0.0:
        raise RouteValidationError('{} must be non-negative'.format(field))
    return value
