"""Pure structured-alarm validation, deduplication and JSON compatibility."""

from dataclasses import asdict, dataclass
import json
import math


INFO = 0
WARNING = 1
ERROR = 2
CRITICAL = 3
_SEVERITIES = {INFO, WARNING, ERROR, CRITICAL}


@dataclass(frozen=True)
class AlarmRecord:
    """ROS-independent representation of car_interfaces/Alarm."""

    severity: int
    code: str
    source: str
    state: str
    message: str
    active: bool = True

    def __post_init__(self):
        if self.severity not in _SEVERITIES:
            raise ValueError('severity must be INFO..CRITICAL')
        for field in ('code', 'source', 'state', 'message'):
            value = getattr(self, field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError('{} must be a non-empty string'.format(field))
        if not isinstance(self.active, bool):
            raise ValueError('active must be boolean')

    @property
    def key(self):
        """Return the stable deduplication identity."""
        return self.source, self.code

    def to_dict(self, stamp_sec=None):
        """Return a JSON-compatible console event dictionary."""
        data = asdict(self)
        if stamp_sec is not None:
            stamp_sec = float(stamp_sec)
            if not math.isfinite(stamp_sec):
                raise ValueError('stamp_sec must be finite')
            data['stamp_sec'] = stamp_sec
        return data


class AlarmDeduplicator:
    """Suppress identical alarms while allowing a controlled heartbeat."""

    def __init__(self, repeat_sec=5.0):
        self.repeat_sec = max(0.1, float(repeat_sec))
        self._last = {}

    def should_emit(self, record, now):
        """Return true for changes or an active-alarm repeat interval."""
        if not isinstance(record, AlarmRecord):
            raise TypeError('record must be AlarmRecord')
        now = float(now)
        previous = self._last.get(record.key)
        changed = previous is None or previous[0] != record
        repeated = (
            previous is not None
            and record.active
            and now - previous[1] >= self.repeat_sec
        )
        if changed or repeated:
            self._last[record.key] = (record, now)
            return True
        return False


def alarm_json(record, stamp_sec=None):
    """Serialize an AlarmRecord for the legacy `/alarm_events` stream."""
    if not isinstance(record, AlarmRecord):
        raise TypeError('record must be AlarmRecord')
    return json.dumps(
        record.to_dict(stamp_sec), ensure_ascii=False,
        sort_keys=True, separators=(',', ':'))
