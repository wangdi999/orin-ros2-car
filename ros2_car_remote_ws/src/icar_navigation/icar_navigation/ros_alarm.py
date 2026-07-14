"""ROS publishers for the typed and legacy-compatible alarm contracts."""

import time

from car_interfaces.msg import Alarm
from std_msgs.msg import String

from .alarm_utils import AlarmDeduplicator, AlarmRecord, alarm_json


class RosAlarmPublisher:
    """Publish deduplicated Alarm messages and equivalent JSON events."""

    def __init__(self, node, repeat_sec=5.0):
        self.node = node
        self.typed_publisher = node.create_publisher(Alarm, '/alarm', 50)
        self.event_publisher = node.create_publisher(String, '/alarm_events', 50)
        self.deduplicator = AlarmDeduplicator(repeat_sec=repeat_sec)

    def publish(self, severity, code, state, message, *, active=True):
        """Publish when state changed or the active repeat interval elapsed."""
        record = AlarmRecord(
            severity=int(severity),
            code=str(code),
            source=self.node.get_name(),
            state=str(state),
            message=str(message),
            active=bool(active),
        )
        now_monotonic = time.monotonic()
        if not self.deduplicator.should_emit(record, now_monotonic):
            return False

        stamp = self.node.get_clock().now()
        message_ros = Alarm()
        message_ros.header.stamp = stamp.to_msg()
        message_ros.severity = record.severity
        message_ros.code = record.code
        message_ros.source = record.source
        message_ros.state = record.state
        message_ros.message = record.message
        message_ros.active = record.active
        self.typed_publisher.publish(message_ros)

        stamp_sec = stamp.nanoseconds / 1_000_000_000.0
        self.event_publisher.publish(String(
            data=alarm_json(record, stamp_sec=stamp_sec)))
        return True
