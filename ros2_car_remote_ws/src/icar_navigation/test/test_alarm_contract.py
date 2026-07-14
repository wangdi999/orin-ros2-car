"""Tests for structured Alarm validation and compatibility JSON."""

import json
import unittest

from icar_navigation.alarm_utils import (
    CRITICAL,
    ERROR,
    AlarmDeduplicator,
    AlarmRecord,
    alarm_json,
)


class TestAlarmContract(unittest.TestCase):
    """Verify stable fields, severity and active/cleared deduplication."""

    def record(self, **overrides):
        values = {
            'severity': ERROR,
            'code': 'SCAN_STALE',
            'source': 'safety_manager',
            'state': 'SENSOR_FAULT',
            'message': 'laser scan is stale',
            'active': True,
        }
        values.update(overrides)
        return AlarmRecord(**values)

    def test_json_contains_every_public_contract_field(self):
        payload = json.loads(alarm_json(self.record(), stamp_sec=12.5))
        self.assertEqual(payload['severity'], ERROR)
        self.assertEqual(payload['code'], 'SCAN_STALE')
        self.assertEqual(payload['source'], 'safety_manager')
        self.assertEqual(payload['state'], 'SENSOR_FAULT')
        self.assertEqual(payload['message'], 'laser scan is stale')
        self.assertTrue(payload['active'])
        self.assertEqual(payload['stamp_sec'], 12.5)

    def test_invalid_severity_empty_fields_and_active_type_are_rejected(self):
        with self.assertRaises(ValueError):
            self.record(severity=9)
        with self.assertRaises(ValueError):
            self.record(code='')
        with self.assertRaises(ValueError):
            self.record(active=1)

    def test_duplicate_active_alarm_is_throttled_but_change_emits(self):
        deduplicator = AlarmDeduplicator(repeat_sec=5.0)
        record = self.record()
        self.assertTrue(deduplicator.should_emit(record, 0.0))
        self.assertFalse(deduplicator.should_emit(record, 1.0))
        self.assertTrue(deduplicator.should_emit(record, 5.0))
        critical = self.record(severity=CRITICAL)
        self.assertTrue(deduplicator.should_emit(critical, 5.1))

    def test_clear_event_emits_once_and_uses_same_identity(self):
        deduplicator = AlarmDeduplicator()
        active = self.record()
        cleared = self.record(active=False, message='laser scan recovered')
        self.assertEqual(active.key, cleared.key)
        self.assertTrue(deduplicator.should_emit(active, 0.0))
        self.assertTrue(deduplicator.should_emit(cleared, 1.0))
        self.assertFalse(deduplicator.should_emit(cleared, 10.0))


if __name__ == '__main__':
    unittest.main()
