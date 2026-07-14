"""Pure command arbitration policy with no ROS dependencies."""

from dataclasses import dataclass
import math
from typing import Dict, Optional


NONE = 'NONE'
ZEROING = 'ZEROING'
MANUAL = 'MANUAL'
NAVIGATION = 'NAVIGATION'
RETURN_HOME = 'RETURN_HOME'
BLOCKED = 'BLOCKED'

READY = 'READY'
LOW_BATTERY_RETURN = 'LOW_BATTERY_RETURN'


@dataclass(frozen=True)
class TwistCommand:
    """The three chassis command components used by this project."""

    linear_x: float = 0.0
    linear_y: float = 0.0
    angular_z: float = 0.0

    @classmethod
    def zero(cls):
        """Return an explicit all-zero command."""
        return cls()

    def is_finite(self):
        """Return true only when all command components are finite."""
        return all(math.isfinite(value) for value in (
            self.linear_x, self.linear_y, self.angular_z))

    def limited(self, max_linear_x, max_linear_y, max_angular_z,
                force_zero_y=False):
        """Return a symmetrically clamped command."""
        if not self.is_finite():
            raise ValueError('command contains NaN or infinity')
        return TwistCommand(
            _clamp(self.linear_x, max_linear_x),
            0.0 if force_zero_y else _clamp(self.linear_y, max_linear_y),
            _clamp(self.angular_z, max_angular_z),
        )


@dataclass(frozen=True)
class ArbitrationDecision:
    """A single deterministic arbiter output."""

    command: TwistCommand
    active_source: str
    cancel_navigation: bool = False
    reason: str = ''


@dataclass
class _Request:
    command: TwistCommand
    received_at: float


def _clamp(value, limit):
    limit = abs(float(limit))
    return max(-limit, min(limit, float(value)))


class MotionPolicy:
    """Priority, freshness and zero-before-switch behavior."""

    def __init__(self, *, manual_timeout_sec=0.30, nav_timeout_sec=0.30,
                 safety_state_timeout_sec=0.30,
                 chassis_state_timeout_sec=0.30,
                 patrol_status_timeout_sec=0.30,
                 max_linear_x=0.10, max_linear_y=0.10,
                 max_angular_z=0.40, zero_cycles_on_switch=1):
        self.manual_timeout_sec = float(manual_timeout_sec)
        self.nav_timeout_sec = float(nav_timeout_sec)
        self.safety_state_timeout_sec = float(safety_state_timeout_sec)
        self.chassis_state_timeout_sec = float(chassis_state_timeout_sec)
        self.patrol_status_timeout_sec = float(patrol_status_timeout_sec)
        self.max_linear_x = float(max_linear_x)
        self.max_linear_y = float(max_linear_y)
        self.max_angular_z = float(max_angular_z)
        self.zero_cycles_on_switch = max(1, int(zero_cycles_on_switch))

        self._manual: Optional[_Request] = None
        self._navigation: Optional[_Request] = None
        self._safety_state: Optional[str] = None
        self._safety_received_at: Optional[float] = None
        self._chassis_connected: Optional[bool] = None
        self._chassis_received_at: Optional[float] = None
        self._patrol_status: Optional[Dict[str, object]] = None
        self._patrol_received_at: Optional[float] = None
        self._active_source = NONE
        self._pending_source: Optional[str] = None
        self._zero_cycles_remaining = 0
        self._navigation_inhibited = False

    def update_manual(self, command, now):
        """Store a finite manual request, returning whether it was accepted."""
        return self._update_request('manual', command, now)

    def update_navigation(self, command, now):
        """Store a finite navigation request with lateral motion removed."""
        return self._update_request('navigation', command, now)

    def update_safety_state(self, state, now):
        """Refresh the authoritative safety heartbeat."""
        previous = self._safety_state
        self._safety_state = str(state)
        self._safety_received_at = float(now)
        if self._safety_state == READY and previous not in (None, READY):
            self._navigation_inhibited = False

    def update_chassis_state(self, connected, now):
        """Refresh the direct fast-stop chassis interlock heartbeat."""
        self._chassis_connected = bool(connected)
        self._chassis_received_at = float(now)

    def update_patrol_status(self, status, now):
        """Refresh parsed patrol status used for return-home authorization."""
        previous = self._patrol_status
        self._patrol_status = dict(status) if isinstance(status, dict) else None
        self._patrol_received_at = float(now)
        if (isinstance(self._patrol_status, dict)
                and self._patrol_status.get('state') == 'NAVIGATING'
                and isinstance(previous, dict)
                and previous.get('state') == 'IDLE'):
            self._navigation_inhibited = False

    def decide(self, now):
        """Compute the next output without side effects outside this object."""
        now = float(now)
        desired, command, reason = self._desired_source(now)

        if desired == BLOCKED:
            cancel = self._active_source in (NAVIGATION, RETURN_HOME)
            self._active_source = BLOCKED
            self._pending_source = None
            self._zero_cycles_remaining = 0
            return ArbitrationDecision(TwistCommand.zero(), BLOCKED, cancel, reason)

        if desired == NONE:
            cancel = self._active_source in (NAVIGATION, RETURN_HOME)
            self._active_source = NONE
            self._pending_source = None
            self._zero_cycles_remaining = 0
            return ArbitrationDecision(TwistCommand.zero(), NONE, cancel, reason)

        if desired != self._active_source:
            if self._pending_source != desired:
                self._pending_source = desired
                self._zero_cycles_remaining = self.zero_cycles_on_switch
                if desired == MANUAL and self._navigation_is_fresh(now):
                    self._navigation_inhibited = True
            if self._zero_cycles_remaining > 0:
                self._zero_cycles_remaining -= 1
                cancel = desired == MANUAL and self._navigation_is_fresh(now)
                return ArbitrationDecision(
                    TwistCommand.zero(), ZEROING, cancel,
                    'zero-before-source-switch')
            self._active_source = desired
            self._pending_source = None

        return ArbitrationDecision(command, self._active_source, False, reason)

    def _update_request(self, source, command, now):
        if not isinstance(command, TwistCommand) or not command.is_finite():
            if source == 'manual':
                self._manual = None
            else:
                self._navigation = None
            return False
        request = _Request(command=command, received_at=float(now))
        if source == 'manual':
            self._manual = request
        else:
            self._navigation = request
        return True

    def _desired_source(self, now):
        if not self._is_fresh(
                self._chassis_received_at,
                self.chassis_state_timeout_sec,
                now):
            return BLOCKED, TwistCommand.zero(), 'chassis-state-stale'
        if not self._chassis_connected:
            return BLOCKED, TwistCommand.zero(), 'chassis-disconnected'

        if not self._is_fresh(
                self._safety_received_at, self.safety_state_timeout_sec, now):
            return BLOCKED, TwistCommand.zero(), 'safety-state-stale'

        if self._safety_state == LOW_BATTERY_RETURN:
            if not self._return_home_authorized(now):
                return BLOCKED, TwistCommand.zero(), 'return-home-not-authorized'
            if not self._navigation_is_fresh(now):
                return NONE, TwistCommand.zero(), 'return-home-command-stale'
            return (
                RETURN_HOME,
                self._navigation.command.limited(
                    self.max_linear_x, 0.0, self.max_angular_z,
                    force_zero_y=True),
                'authorized-return-home',
            )

        if self._safety_state != READY:
            return BLOCKED, TwistCommand.zero(), 'safety-state-blocked'

        if self._manual_is_fresh(now):
            return (
                MANUAL,
                self._manual.command.limited(
                    self.max_linear_x, self.max_linear_y,
                    self.max_angular_z),
                'manual-priority',
            )
        if self._navigation_is_fresh(now):
            if self._navigation_inhibited:
                return NONE, TwistCommand.zero(), 'navigation-inhibited'
            if self._patrol_blocks_navigation(now):
                return NONE, TwistCommand.zero(), 'patrol-transition-blocked'
            return (
                NAVIGATION,
                self._navigation.command.limited(
                    self.max_linear_x, 0.0, self.max_angular_z,
                    force_zero_y=True),
                'navigation',
            )
        return NONE, TwistCommand.zero(), 'no-fresh-request'

    def _return_home_authorized(self, now):
        if not self._is_fresh(
                self._patrol_received_at, self.patrol_status_timeout_sec, now):
            return False
        return (
            isinstance(self._patrol_status, dict)
            and self._patrol_status.get('mode') == RETURN_HOME
            and self._patrol_status.get('state') == 'NAVIGATING'
        )

    def _patrol_blocks_navigation(self, now):
        if not self._is_fresh(
                self._patrol_received_at, self.patrol_status_timeout_sec, now):
            return False
        if not isinstance(self._patrol_status, dict):
            return True
        return self._patrol_status.get('state') in {
            'ARRIVED', 'WAITING', 'NEXT_GOAL', 'CANCELLING'}

    def _manual_is_fresh(self, now):
        return self._request_is_fresh(self._manual, self.manual_timeout_sec, now)

    def _navigation_is_fresh(self, now):
        return self._request_is_fresh(
            self._navigation, self.nav_timeout_sec, now)

    @staticmethod
    def _is_fresh(received_at, timeout, now):
        if received_at is None:
            return False
        age = float(now) - float(received_at)
        return 0.0 <= age <= float(timeout)

    @classmethod
    def _request_is_fresh(cls, request, timeout, now):
        return request is not None and cls._is_fresh(
            request.received_at, timeout, now)
