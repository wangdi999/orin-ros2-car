import assert from 'node:assert/strict';
import { test } from 'node:test';
import { recomputeCanDrive, runtime } from './state.mjs';

function setRequiredDriveState() {
  runtime.status.devices = {
    chassisSerial: true,
    lidar: true,
    cameraDepth: false,
    cameraUvc: false,
    video0: true
  };
  runtime.status.services = {
    chassis: true,
    lidar: true,
    camera: false,
    video: true,
    rosbridge: true
  };
  runtime.status.ports.rosbridge9090 = true;
}

test('an open remote port does not replace the local rosbridge connection', () => {
  setRequiredDriveState();
  runtime.rosbridge.connected = false;

  recomputeCanDrive();

  assert.equal(runtime.status.canDrive, false);
  assert.equal(runtime.status.blockers.includes('ROSBridge is not connected'), true);
});

test('drive becomes available after the local rosbridge websocket connects', () => {
  setRequiredDriveState();
  runtime.rosbridge.connected = true;

  recomputeCanDrive();

  assert.equal(runtime.status.canDrive, true);
  assert.deepEqual(runtime.status.blockers, []);
});
