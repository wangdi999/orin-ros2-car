import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  addLog,
  bus,
  clearEmergencyStop,
  clearPerceptionTelemetry,
  configureHeartbeat,
  markEmergencyStop,
  recomputeCanDrive,
  runtime,
  snapshot,
  telemetry,
  updateTelemetry,
  updateNavigation
} from './state.mjs';

test('heartbeat config sync does not create a heartbeat timestamp', () => {
  runtime.command.heartbeat = {
    connected: false,
    lastAt: null,
    ageMs: null,
    intervalMs: 100,
    timeoutMs: 500,
    protectionEnabled: true
  };

  configureHeartbeat({
    timeoutMs: 500,
    protectionEnabled: false
  });

  const heartbeat = snapshot().runtime.command.heartbeat;
  assert.equal(heartbeat.lastAt, null);
  assert.equal(heartbeat.ageMs, null);
  assert.equal(heartbeat.connected, true);
  assert.equal(heartbeat.protectionEnabled, false);
});

test('authoritative safety state blocks drive until READY', () => {
  updateNavigation({ safetyState: 'ESTOP' });
  let current = snapshot();
  assert.equal(current.runtime.safety.emergencyStopActive, true);
  assert.equal(current.runtime.status.blockers.includes('Safety state is ESTOP'), true);

  updateNavigation({ safetyState: 'READY' });
  current = snapshot();
  assert.equal(current.runtime.status.blockers.includes('Safety state is READY'), false);
  assert.equal(current.runtime.safety.emergencyStopActive, true);
});

test('public telemetry omits unsupported environment, accessory power, encoder, current and power fields', () => {
  const current = snapshot().telemetry;

  assert.equal(current.environment, undefined);
  assert.equal(current.accessoryPower, undefined);
  assert.equal(current.encoders, undefined);
  assert.equal(current.voltage.current, undefined);
  assert.equal(current.voltage.power, undefined);
  assert.equal(current.voltage.percentEstimated, true);
});

test('stale telemetry retains the last real payload and adds a disconnect reason', () => {
  updateTelemetry({
    pointCloud: {
      connected: true,
      points: [{ x: 1, y: 2, z: 3 }],
      updatedAt: new Date(Date.now() - 5001).toISOString()
    }
  });

  const current = snapshot().telemetry.pointCloud;
  assert.equal(current.stale, true);
  assert.deepEqual(current.points, [{ x: 1, y: 2, z: 3 }]);
  assert.match(current.disconnectedReason, /5 秒/);
  telemetry.pointCloud.connected = false;
});

test('high-rate telemetry emits an incremental patch instead of a full snapshot', () => {
  let telemetryEvents = 0;
  let snapshotEvents = 0;
  const onTelemetry = () => { telemetryEvents += 1; };
  const onSnapshot = () => { snapshotEvents += 1; };
  bus.on('telemetry', onTelemetry);
  bus.on('snapshot', onSnapshot);
  updateTelemetry({ velocity: { connected: true, linear: 0, angular: 0 } });
  bus.off('telemetry', onTelemetry);
  bus.off('snapshot', onSnapshot);
  assert.equal(telemetryEvents, 1);
  assert.equal(snapshotEvents, 0);
});

test('disabling perception preview releases image, point-cloud, tracking and detection payloads', () => {
  updateTelemetry({
    camera: { connected: true, dataUrl: 'data:image/jpeg;base64,large', pixels: [[1, 2, 3]] },
    depth: { connected: true, values: [1, 2] },
    ir: { connected: true, values: [3, 4] },
    pointCloud: { connected: true, points: [{ x: 1, y: 2, z: 3 }] },
    tracking: { connected: true, image: { dataUrl: 'data:image/jpeg;base64,large' }, shadowTwist: { linear: { x: 1 } } },
    detections: { connected: true, detections: [{ label: 'target' }], count: 1 }
  });

  clearPerceptionTelemetry();
  assert.equal(telemetry.camera.connected, false);
  assert.equal(telemetry.camera.dataUrl, null);
  assert.deepEqual(telemetry.camera.pixels, []);
  assert.deepEqual(telemetry.depth.values, []);
  assert.deepEqual(telemetry.ir.values, []);
  assert.deepEqual(telemetry.pointCloud.points, []);
  assert.equal(telemetry.tracking.image, null);
  assert.equal(telemetry.tracking.shadowTwist, null);
  assert.deepEqual(telemetry.detections.detections, []);
  assert.equal(telemetry.detections.count, 0);
});

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
