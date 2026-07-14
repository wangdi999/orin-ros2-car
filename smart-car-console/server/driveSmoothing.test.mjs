import assert from 'node:assert/strict';
import test from 'node:test';
import {
  DRIVE_PUBLISH_INTERVAL_MS,
  HEARTBEAT_INTERVAL_MS,
  JOYSTICK_ALPHA,
  WATCHDOG_TIMEOUT_MS,
  hasMotion,
  smoothJoystickVector
} from '../src/driveSmoothing.js';

test('joystick smoothing uses alpha 0.3 and rounds axes', () => {
  const next = smoothJoystickVector(
    { forward: 0, turn: 0.5, strafe: 0 },
    { forward: 1, turn: -0.5, strafe: 0 },
    JOYSTICK_ALPHA
  );
  assert.deepEqual(next, { forward: 0.3, turn: 0.2, strafe: 0 });
});

test('drive cadence and heartbeat constants match safety plan', () => {
  assert.equal(DRIVE_PUBLISH_INTERVAL_MS, 50);
  assert.equal(HEARTBEAT_INTERVAL_MS, 100);
  assert.equal(WATCHDOG_TIMEOUT_MS, 500);
  assert.equal(hasMotion({ forward: 0.02, turn: 0, strafe: 0 }), true);
  assert.equal(hasMotion({ forward: 0.001, turn: 0, strafe: 0 }), false);
});
