"""Pure safety helpers for the X3 chassis driver."""

from dataclasses import dataclass
import math
import select
from typing import Iterable, Optional


HARD_LINEAR_LIMIT = 0.50
HARD_ANGULAR_LIMIT = 2.00
HARD_COMMAND_TIMEOUT_SEC = 0.30


@dataclass(frozen=True)
class SafeMotion:
    """A finite, hard-limited chassis command."""

    linear_x: float
    linear_y: float
    angular_z: float


class DriverSafety:
    """Hard limits and a one-shot command watchdog."""

    def __init__(self, *, x_limit=HARD_LINEAR_LIMIT,
                 y_limit=HARD_LINEAR_LIMIT,
                 angular_limit=HARD_ANGULAR_LIMIT,
                 command_timeout_sec=0.30):
        self.x_limit = _safe_limit(x_limit, HARD_LINEAR_LIMIT)
        self.y_limit = _safe_limit(y_limit, HARD_LINEAR_LIMIT)
        self.angular_limit = _safe_limit(angular_limit, HARD_ANGULAR_LIMIT)
        self.command_timeout_sec = min(
            HARD_COMMAND_TIMEOUT_SEC, max(0.05, float(command_timeout_sec)))
        self._last_command_at: Optional[float] = None
        self._watchdog_zero_sent = True

    def sanitize(self, linear_x, linear_y, angular_z):
        """Return a hard-limited command, or None for any non-finite input."""
        values = (linear_x, linear_y, angular_z)
        try:
            values = tuple(float(value) for value in values)
        except (TypeError, ValueError):
            return None
        if not all(math.isfinite(value) for value in values):
            return None
        return SafeMotion(
            _clamp(values[0], self.x_limit),
            _clamp(values[1], self.y_limit),
            _clamp(values[2], self.angular_limit),
        )

    def record_valid_command(self, now):
        """Refresh watchdog time after hardware accepted a valid command."""
        self._last_command_at = float(now)
        self._watchdog_zero_sent = False

    def watchdog_zero_due(self, now):
        """Return true exactly once after a command becomes stale."""
        if self._last_command_at is None or self._watchdog_zero_sent:
            return False
        age = float(now) - self._last_command_at
        if age < 0.0 or age + 1e-9 >= self.command_timeout_sec:
            self._watchdog_zero_sent = True
            return True
        return False

    def mark_zero_sent(self):
        """Suppress repeated watchdog zeros until another command arrives."""
        self._watchdog_zero_sent = True


class ReconnectBackoff:
    """A deterministic fixed-interval reconnect schedule."""

    def __init__(self, interval_sec=5.0):
        self.interval_sec = max(1.0, float(interval_sec))
        self.connected = False
        self._last_attempt_at: Optional[float] = None

    def mark_connected(self):
        """Record a healthy serial connection."""
        self.connected = True
        self._last_attempt_at = None

    def mark_disconnected(self, now):
        """Start a retry interval without causing an immediate busy loop."""
        self.connected = False
        if self._last_attempt_at is None:
            self._last_attempt_at = float(now)

    def retry_due(self, now):
        """Return true when another connection attempt is allowed."""
        if self.connected:
            return False
        if self._last_attempt_at is None:
            return True
        return float(now) - self._last_attempt_at >= self.interval_sec

    def record_attempt(self, now):
        """Delay the next reconnect by the full configured interval."""
        self._last_attempt_at = float(now)


def exclusive_publisher_matches(publishers: Iterable[object],
                                expected_node_name: str) -> bool:
    """Require exactly one publisher whose node name matches the arbiter."""
    names = []
    for publisher in publishers:
        if isinstance(publisher, str):
            name = publisher
        elif isinstance(publisher, tuple) and publisher:
            name = publisher[0]
        else:
            name = getattr(publisher, 'node_name', '')
        names.append(str(name).lstrip('/'))
    return names == [str(expected_node_name).lstrip('/')]


def serial_endpoint_is_healthy(serial_port, poll_factory=None) -> bool:
    """Reject closed or kernel-hung-up serial file descriptors."""
    if serial_port is None or not bool(getattr(serial_port, 'is_open', False)):
        return False
    try:
        descriptor = int(serial_port.fileno())
    except (AttributeError, OSError, TypeError, ValueError):
        return False
    if descriptor < 0:
        return False

    factory = poll_factory or getattr(select, 'poll', None)
    if factory is None:
        return True
    error_mask = (
        getattr(select, 'POLLERR', 0x08)
        | getattr(select, 'POLLHUP', 0x10)
        | getattr(select, 'POLLNVAL', 0x20)
    )
    try:
        poller = factory()
        poller.register(descriptor, error_mask)
        events = poller.poll(0)
    except (OSError, TypeError, ValueError):
        return False
    return not any(mask & error_mask for _, mask in events)


def _safe_limit(configured, hard_limit):
    try:
        configured = abs(float(configured))
    except (TypeError, ValueError):
        configured = hard_limit
    if not math.isfinite(configured) or configured <= 0.0:
        configured = hard_limit
    return min(configured, hard_limit)


def _clamp(value, limit):
    return max(-limit, min(limit, value))
