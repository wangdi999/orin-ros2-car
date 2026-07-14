import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { AlarmManager } from './alarmManager.mjs';
import { runtime, telemetry, updateAlarms } from './state.mjs';

test('AlarmManager raises, deduplicates, acknowledges, resolves, and persists alarms', async () => {
  const dir = await mkdtemp(path.join(os.tmpdir(), 'smartcar-alarms-'));
  const storage = path.join(dir, 'alarms.json');
  try {
    updateAlarms({ items: [], summary: { total: 0, active: 0, acknowledged: 0, resolved: 0, critical: 0, warning: 0 } });
    const manager = new AlarmManager(storage);
    await manager.load();

    const first = manager.raise({
      source: 'safety',
      type: 'watchdog',
      severity: 'critical',
      title: 'Watchdog',
      message: 'timeout',
      dedupeKey: 'safety:watchdog'
    });
    const second = manager.raise({
      source: 'safety',
      type: 'watchdog',
      severity: 'critical',
      title: 'Watchdog',
      message: 'timeout again',
      dedupeKey: 'safety:watchdog'
    });

    assert.equal(first.id, second.id);
    assert.equal(runtime.alarms.items.length, 1);
    assert.equal(runtime.alarms.items[0].count, 2);
    assert.equal(manager.ack(first.id).status, 'acknowledged');
    assert.equal(manager.resolve(first.id).status, 'resolved');
    await manager.persist();

    updateAlarms({ items: [], summary: { total: 0, active: 0, acknowledged: 0, resolved: 0, critical: 0, warning: 0 } });
    const reloaded = new AlarmManager(storage);
    await reloaded.load();
    assert.equal(runtime.alarms.items.length, 1);
    assert.equal(runtime.alarms.items[0].status, 'resolved');
    clearTimeout(manager.persistTimer);
    clearTimeout(reloaded.persistTimer);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test('AlarmManager evaluates low voltage and near lidar obstacles', () => {
  updateAlarms({ items: [], summary: { total: 0, active: 0, acknowledged: 0, resolved: 0, critical: 0, warning: 0 } });
  telemetry.voltage = { ...telemetry.voltage, battery: 10.1, connected: true };
  telemetry.lidar = { ...telemetry.lidar, connected: true, points: [{ range: 0.24, angle: 0 }] };
  runtime.status.blockers = [];
  runtime.rosbridge.url = null;
  runtime.safety.emergencyStopActive = false;

  const manager = new AlarmManager(path.join(os.tmpdir(), 'unused-smartcar-alarms.json'));
  manager.evaluate();

  assert.ok(runtime.alarms.items.some((item) => item.type === 'low_voltage' && item.severity === 'critical'));
  assert.ok(runtime.alarms.items.some((item) => item.type === 'near_obstacle'));
  clearTimeout(manager.persistTimer);
});

test('typed car alarm clear resolves the matching active alarm', () => {
  updateAlarms({ items: [], summary: { total: 0, active: 0, acknowledged: 0, resolved: 0, critical: 0, warning: 0 } });
  const manager = new AlarmManager(path.join(os.tmpdir(), 'unused-typed-smartcar-alarms.json'));
  const raised = manager.ingestCarAlarm({
    source: 'safety_manager',
    type: 'ODOM_TF_STALE',
    severity: 'critical',
    message: 'odometry is stale',
    active: true,
    dedupeKey: 'safety_manager:ODOM_TF_STALE'
  });
  assert.equal(raised.status, 'active');

  const cleared = manager.ingestCarAlarm({
    source: 'safety_manager',
    type: 'ODOM_TF_STALE',
    active: false,
    dedupeKey: 'safety_manager:ODOM_TF_STALE'
  });
  assert.equal(cleared.id, raised.id);
  assert.equal(cleared.status, 'resolved');
  clearTimeout(manager.persistTimer);
});
