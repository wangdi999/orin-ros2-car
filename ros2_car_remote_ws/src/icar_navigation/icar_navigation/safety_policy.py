"""Pure safety latch and low-battery policies."""

from collections import deque
from dataclasses import dataclass
import math
from typing import Optional


INITIALIZING = 'INITIALIZING'
READY = 'READY'
ESTOP = 'ESTOP'
CHASSIS_FAULT = 'CHASSIS_FAULT'
SENSOR_FAULT = 'SENSOR_FAULT'
ODOM_TF_FAULT = 'ODOM_TF_FAULT'
OWNERSHIP_FAULT = 'OWNERSHIP_FAULT'
LOW_BATTERY_RETURN = 'LOW_BATTERY_RETURN'
RETURNED_HOME = 'RETURNED_HOME'
RETURN_FAILED = 'RETURN_FAILED'


@dataclass(frozen=True)
class HealthSnapshot:
    """Safety-relevant health facts at one monotonic instant."""

    chassis_connected: bool = False
    chassis_age_sec: float = math.inf
    scan_age_sec: float = math.inf
    odom_age_sec: float = math.inf
    tf_complete: bool = False
    ownership_valid: bool = False


class BatteryMonitor:
    """Ten-sample mean with sustained-low and recovery hysteresis."""

    def __init__(self, window_size=10, threshold_v=10.8,
                 recovery_v=11.1, sustain_sec=5.0):
        self.window_size = max(1, int(window_size))
        self.threshold_v = float(threshold_v)
        self.recovery_v = float(recovery_v)
        self.sustain_sec = float(sustain_sec)
        self._samples = deque(maxlen=self.window_size)
        self._low_since: Optional[float] = None
        self._triggered = False

    @property
    def average(self):
        """Return the current finite mean or None before any valid sample."""
        if not self._samples:
            return None
        return sum(self._samples) / len(self._samples)

    @property
    def triggered(self):
        """Return the current hysteretic low-battery state."""
        return self._triggered

    def add_sample(self, voltage, now, enabled=False):
        """Add one finite voltage sample and return whether real trigger is active."""
        try:
            voltage = float(voltage)
        except (TypeError, ValueError):
            return self._triggered
        if not math.isfinite(voltage):
            return self._triggered
        now = float(now)
        self._samples.append(voltage)
        average = self.average

        if average is not None and average + 1e-9 >= self.recovery_v:
            self._low_since = None
            self._triggered = False
            return False

        if not enabled or len(self._samples) < self.window_size:
            self._low_since = None
            return False

        if average <= self.threshold_v + 1e-9:
            if self._low_since is None:
                self._low_since = now
            if now - self._low_since >= self.sustain_sec:
                self._triggered = True
        else:
            self._low_since = None
        return self._triggered


class SafetyPolicy:
    """Fail-closed startup, latching faults and explicit reset policy."""

    _FAULT_STATES = {
        ESTOP, CHASSIS_FAULT, SENSOR_FAULT, ODOM_TF_FAULT,
        OWNERSHIP_FAULT, RETURN_FAILED,
    }

    def __init__(self, *, started_at=0.0, startup_grace_sec=5.0,
                 chassis_timeout_sec=0.30, scan_timeout_sec=0.40,
                 odom_timeout_sec=0.20):
        self.started_at = float(started_at)
        self.startup_grace_sec = float(startup_grace_sec)
        self.chassis_timeout_sec = float(chassis_timeout_sec)
        self.scan_timeout_sec = float(scan_timeout_sec)
        self.odom_timeout_sec = float(odom_timeout_sec)
        self.state = INITIALIZING
        self.estop_input = False
        self.last_reason = 'startup'

    def set_estop(self, requested):
        """Latch emergency stop on true; false only clears the input."""
        self.estop_input = bool(requested)
        if self.estop_input:
            self.state = ESTOP
            self.last_reason = 'emergency stop requested'

    def evaluate(self, health, now):
        """Apply current health without automatically clearing a latch."""
        now = float(now)
        if self.estop_input:
            self.state = ESTOP
            self.last_reason = 'emergency stop requested'
            return self.state

        if self.state in self._FAULT_STATES or self.state in {
                LOW_BATTERY_RETURN, RETURNED_HOME}:
            return self.state

        if now - self.started_at < self.startup_grace_sec:
            self.state = INITIALIZING
            self.last_reason = 'startup grace period'
            return self.state

        fault, reason = self._current_fault(health)
        if fault is not None:
            self.state = fault
            self.last_reason = reason
            return self.state

        self.state = READY
        self.last_reason = 'all required health checks pass'
        return self.state

    def request_low_battery_return(self, health, now):
        """Enter controlled return only when ordinary motion is safe."""
        if self.evaluate(health, now) != READY:
            return False, 'safety state is not READY'
        self.state = LOW_BATTERY_RETURN
        self.last_reason = 'low battery return requested'
        return True, self.last_reason

    def report_return_result(self, succeeded):
        """Latch the terminal result of a controlled return."""
        if self.state != LOW_BATTERY_RETURN:
            return False
        self.state = RETURNED_HOME if succeeded else RETURN_FAILED
        self.last_reason = 'home reached' if succeeded else 'return home failed'
        return True

    def force_return_failed(self, reason):
        """Fail closed when a real low-battery return cannot be started."""
        self.state = RETURN_FAILED
        self.last_reason = str(reason) or 'return home failed'

    def reset(self, health, now, *, action_active=False, output_is_zero=True):
        """Clear an eligible latch only when every reset precondition passes."""
        if self.estop_input:
            return False, 'emergency stop input is still active'
        if action_active:
            return False, 'an autonomous action is still active'
        if not output_is_zero:
            return False, 'final command output is not zero'
        fault, reason = self._current_fault(health)
        if fault is not None:
            return False, reason
        if self.state == LOW_BATTERY_RETURN:
            return False, 'return-home action has not completed'
        if float(now) - self.started_at < self.startup_grace_sec:
            return False, 'startup grace period is not complete'
        self.state = READY
        self.last_reason = 'explicit reset accepted'
        return True, self.last_reason

    def _current_fault(self, health):
        if not isinstance(health, HealthSnapshot):
            return OWNERSHIP_FAULT, 'health snapshot is unavailable'
        if not health.ownership_valid:
            return OWNERSHIP_FAULT, 'topic or mode ownership does not match contract'
        if (not health.chassis_connected
                or not _fresh(health.chassis_age_sec, self.chassis_timeout_sec)):
            return CHASSIS_FAULT, 'chassis is disconnected or stale'
        if not _fresh(health.scan_age_sec, self.scan_timeout_sec):
            return SENSOR_FAULT, 'laser scan is stale'
        if (not _fresh(health.odom_age_sec, self.odom_timeout_sec)
                or not health.tf_complete):
            return ODOM_TF_FAULT, 'odometry or TF is unavailable'
        return None, ''


def _fresh(age, timeout):
    try:
        age = float(age)
    except (TypeError, ValueError):
        return False
    return math.isfinite(age) and 0.0 <= age <= float(timeout)
