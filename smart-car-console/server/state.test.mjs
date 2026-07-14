import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  addLog,
  clearEmergencyStop,
  markEmergencyStop,
  recomputeCanDrive,
  runtime
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
    arbiter: false,
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

function setRequiredDriveState() {
  resetRuntimeForTest();
  runtime.status.devices.chassisSerial = true;
  runtime.status.devices.lidar = true;
  runtime.status.devices.video0 = true;
  runtime.status.services.chassis = true;
  runtime.status.services.arbiter = true;
  runtime.status.services.lidar = true;
  runtime.status.services.video = true;
  runtime.status.services.rosbridge = true;
  runtime.status.ports.rosbridge9090 = true;
}

test('recomputeCanDrive blocks when chassis or rosbridge is missing', () => {
  resetRuntimeForTest();

  recomputeCanDrive();

  assert.equal(runtime.status.canDrive, false);
  assert.ok(runtime.status.blockers.length > 0);
});

test('an open remote port does not replace the local rosbridge connection', () => {
  setRequiredDriveState();

  recomputeCanDrive();

  assert.equal(runtime.status.canDrive, false);
  assert.equal(runtime.status.blockers.includes('ROSBridge is not connected'), true);
});

test('recomputeCanDrive allows driving when all prerequisites are met', () => {
  setRequiredDriveState();
  runtime.rosbridge.connected = true;

  recomputeCanDrive();

  assert.equal(runtime.status.canDrive, true);
  assert.deepEqual(runtime.status.blockers, []);
});

test('emergency stop clears active command state', () => {
  resetRuntimeForTest();
  runtime.command.active = true;
  runtime.command.lastTwist = {
    linear: { x: 0.1, y: 0, z: 0 },
    angular: { x: 0, y: 0, z: 0 }
  };

  markEmergencyStop('operator');

  assert.equal(runtime.safety.emergencyStopActive, true);
  assert.equal(runtime.safety.lastStopReason, 'operator');
  assert.equal(runtime.command.active, false);
  assert.equal(runtime.command.lastTwist, null);
  clearEmergencyStop();
  assert.equal(runtime.safety.emergencyStopActive, false);
});

test('addLog appends an entry to the bounded log buffer', () => {
  addLog('info', 'test', 'merged-state-test');

  assert.equal(runtime.logs.at(-1).scope, 'test');
  assert.equal(runtime.logs.at(-1).message, 'merged-state-test');
  assert.ok(runtime.logs.length <= 200);
});
