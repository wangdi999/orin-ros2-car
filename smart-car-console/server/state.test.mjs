import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  runtime,
  recomputeCanDrive,
  markEmergencyStop,
  clearEmergencyStop,
  addLog
} from './state.mjs';

function resetRuntimeForTest() {
  runtime.safety.emergencyStopActive = false;
  runtime.safety.lastStopAt = null;
  runtime.safety.lastStopReason = null;
  runtime.command.active = false;
  runtime.command.lastTwist = null;
  runtime.rosbridge.connected = false;
  runtime.status.devices = {
    chassisSerial: false,
    chassisPath: null,
    lidar: false,
    cameraDepth: false,
    cameraUvc: false,
    video0: false
  };
  runtime.status.services = {
    docker: false,
    container: null,
    chassis: false,
    lidar: false,
    camera: false,
    rosbridge: false,
    video: false
  };
  runtime.status.ports = {
    control6000: false,
    video6500: false,
    rosbridge9090: false
  };
}

test('recomputeCanDrive blocks when chassis or rosbridge is missing', () => {
  resetRuntimeForTest();
  recomputeCanDrive();
  assert.equal(runtime.status.canDrive, false);
  assert.ok(runtime.status.blockers.length > 0);
});

test('recomputeCanDrive allows driving when all prerequisites are met', () => {
  resetRuntimeForTest();
  runtime.status.devices.chassisSerial = true;
  runtime.status.devices.lidar = true;
  runtime.status.devices.video0 = true;
  runtime.status.services.chassis = true;
  runtime.status.services.lidar = true;
  runtime.status.services.camera = true;
  runtime.rosbridge.connected = true;
  recomputeCanDrive();
  assert.equal(runtime.status.canDrive, true);
  assert.deepEqual(runtime.status.blockers, []);
});

test('emergency stop clears active command state', () => {
  resetRuntimeForTest();
  runtime.command.active = true;
  runtime.command.lastTwist = { linear: { x: 0.1, y: 0, z: 0 }, angular: { x: 0, y: 0, z: 0 } };
  markEmergencyStop('operator');
  assert.equal(runtime.safety.emergencyStopActive, true);
  assert.equal(runtime.safety.lastStopReason, 'operator');
  assert.equal(runtime.command.active, false);
  assert.equal(runtime.command.lastTwist, null);
  clearEmergencyStop();
  assert.equal(runtime.safety.emergencyStopActive, false);
});

test('addLog keeps log buffer bounded', () => {
  const initialLength = runtime.logs.length;
  for (let i = 0; i < 5; i += 1) {
    addLog('info', 'test', `message-${i}`);
  }
  assert.ok(runtime.logs.length >= initialLength);
  assert.equal(runtime.logs.at(-1).scope, 'test');
});
