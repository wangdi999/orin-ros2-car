"""Pure patrol state transitions and Foxy action-status interpretation."""

from dataclasses import dataclass
from typing import Optional

from .route_loader import RouteConfig, Waypoint, require_executable_route


IDLE = 'IDLE'
NAVIGATING = 'NAVIGATING'
ARRIVED = 'ARRIVED'
WAITING = 'WAITING'
NEXT_GOAL = 'NEXT_GOAL'
CANCELLING = 'CANCELLING'

PATROL = 'PATROL'
RETURN_HOME = 'RETURN_HOME'
SINGLE_GOAL = 'SINGLE_GOAL'

# action_msgs/msg/GoalStatus values in ROS 2 Foxy.
STATUS_SUCCEEDED = 4
STATUS_CANCELED = 5
STATUS_ABORTED = 6


@dataclass(frozen=True)
class Transition:
    """Result of one state transition."""

    event: str
    send_goal: bool = False
    publish_alarm: bool = False
    terminal: bool = False


class PatrolPolicy:
    """Deterministic sequential patrol and return-home policy."""

    def __init__(self):
        self.route: Optional[RouteConfig] = None
        self.state = IDLE
        self.mode = PATROL
        self.index = -1
        self.attempt = 0
        self.reason = ''
        self.single_goal: Optional[Waypoint] = None
        self.goal_id = ''

    @property
    def active(self):
        """Return true while an action or dwell transition is active."""
        return self.state != IDLE

    @property
    def current_waypoint(self) -> Optional[Waypoint]:
        """Return the current goal selected by the policy."""
        if self.route is None:
            return self.single_goal if self.mode == SINGLE_GOAL else None
        if self.mode == SINGLE_GOAL:
            return self.single_goal
        if self.mode == RETURN_HOME:
            return self.route.home
        if 0 <= self.index < len(self.route.waypoints):
            return self.route.waypoints[self.index]
        return None

    def start_patrol(self, route):
        """Start the first route waypoint."""
        require_executable_route(route)
        if self.active:
            return Transition('already-active', terminal=True)
        self.route = route
        self.single_goal = None
        self.goal_id = ''
        self.mode = PATROL
        self.index = 0
        self.attempt = 0
        self.state = NAVIGATING
        self.reason = ''
        return Transition('patrol-started', send_goal=True)

    def start_single_goal(self, waypoint, goal_id=''):
        """Start one map-frame goal without creating a route."""
        if self.active:
            return Transition('already-active', terminal=True)
        if not isinstance(waypoint, Waypoint):
            return Transition('invalid-single-goal', terminal=True)
        self.route = None
        self.single_goal = waypoint
        self.goal_id = str(goal_id)
        self.mode = SINGLE_GOAL
        self.index = -1
        self.attempt = 0
        self.state = NAVIGATING
        self.reason = ''
        return Transition('single-goal-started', send_goal=True)

    def start_return_home(self, route):
        """Cancel logical patrol state and select Home as the only goal."""
        require_executable_route(route)
        self.route = route
        self.single_goal = None
        self.goal_id = ''
        self.mode = RETURN_HOME
        self.index = -1
        self.attempt = 0
        self.state = NAVIGATING
        self.reason = ''
        return Transition('return-home-started', send_goal=True)

    def fail_return_home(self, reason='return_failed'):
        """Publish a fail-closed return result when no goal can be created."""
        self.mode = RETURN_HOME
        self.index = -1
        self.attempt = 0
        self.state = IDLE
        self.reason = 'return_failed'
        return Transition(
            str(reason), publish_alarm=True, terminal=True)

    def handle_goal_result(self, status, *, rejected=False, timed_out=False):
        """Interpret Foxy action status without inspecting the empty result."""
        if self.state != NAVIGATING:
            return Transition('no-active-goal', terminal=True)
        if not rejected and not timed_out and status == STATUS_SUCCEEDED:
            return self._goal_succeeded()
        if status == STATUS_CANCELED:
            self.state = IDLE
            self.reason = 'goal_canceled'
            return Transition('goal-canceled', terminal=True)
        if timed_out:
            reason = 'goal_timeout'
        elif rejected:
            reason = 'goal_rejected'
        elif status == STATUS_ABORTED:
            reason = 'goal_aborted'
        else:
            reason = 'goal_failed_status_{}'.format(status)
        if self.mode == SINGLE_GOAL:
            self.state = IDLE
            self.reason = reason
            return Transition(reason.replace('_', '-'), publish_alarm=True, terminal=True)
        return self._goal_failed(reason)

    def begin_waiting(self):
        """Advance an arrived patrol goal into its dwell state."""
        if self.state != ARRIVED:
            return Transition('not-arrived', terminal=True)
        self.state = WAITING
        return Transition('dwell-started')

    def dwell_elapsed(self):
        """Select the next waypoint or finish the route."""
        if self.state != WAITING:
            return Transition('not-waiting', terminal=True)
        self.state = NEXT_GOAL
        return self.advance_after_next_goal()

    def advance_after_next_goal(self):
        """Move NEXT_GOAL to another navigation goal or IDLE."""
        if self.state != NEXT_GOAL or self.route is None:
            return Transition('not-next-goal', terminal=True)
        self.index += 1
        self.attempt = 0
        if self.index < len(self.route.waypoints):
            self.state = NAVIGATING
            self.reason = ''
            return Transition('next-goal', send_goal=True)
        if self.route.loop:
            self.index = 0
            self.state = NAVIGATING
            self.reason = ''
            return Transition('route-loop', send_goal=True)
        self.state = IDLE
        self.reason = 'route_completed'
        return Transition('route-completed', terminal=True)

    def cancel(self, reason='cancelled'):
        """Enter a cancellable zero-motion terminal path."""
        if self.state == IDLE:
            self.reason = reason
            return Transition('already-idle', terminal=True)
        self.state = CANCELLING
        self.reason = reason
        return Transition('cancel-requested')

    def cancellation_complete(self):
        """Finish cancellation without resuming the prior route."""
        self.state = IDLE
        return Transition('cancel-complete', terminal=True)

    def timeout_cancellation_complete(self, terminal_status=None):
        """Retry/skip only after the timed-out remote goal is terminal."""
        if self.state != CANCELLING:
            return Transition('not-cancelling', terminal=True)
        self.state = NAVIGATING
        if terminal_status == STATUS_SUCCEEDED:
            return self.handle_goal_result(terminal_status)
        return self.handle_goal_result(0, timed_out=True)

    def status_dict(self):
        """Return the stable public status representation."""
        waypoint = self.current_waypoint
        return {
            'state': self.state,
            'mode': self.mode,
            'waypoint': waypoint.name if waypoint else '',
            'index': self.index,
            'attempt': self.attempt,
            'route_configured': bool(
                self.route is not None and self.route.configured),
            'reason': self.reason,
            'goal_id': self.goal_id,
        }

    def _goal_succeeded(self):
        self.attempt = 0
        if self.mode == SINGLE_GOAL:
            self.state = IDLE
            self.reason = 'goal_succeeded'
            return Transition('single-goal-succeeded', terminal=True)
        if self.mode == RETURN_HOME:
            self.state = IDLE
            self.reason = 'home_reached'
            return Transition('home-reached', terminal=True)
        self.state = ARRIVED
        self.reason = ''
        return Transition('goal-arrived')

    def _goal_failed(self, reason):
        if self.route is None:
            self.state = IDLE
            self.reason = reason
            return Transition('route-missing', publish_alarm=True, terminal=True)
        if self.attempt < self.route.max_retries:
            self.attempt += 1
            self.reason = reason
            return Transition('goal-retry', send_goal=True, publish_alarm=True)
        if self.mode == RETURN_HOME:
            self.state = IDLE
            self.reason = 'return_failed'
            return Transition('return-failed', publish_alarm=True, terminal=True)
        if self.route.failure_policy == 'skip':
            self.state = NEXT_GOAL
            self.reason = 'waypoint_skipped'
            return Transition('waypoint-skipped', publish_alarm=True)
        self.state = IDLE
        self.reason = reason
        return Transition('route-aborted', publish_alarm=True, terminal=True)
