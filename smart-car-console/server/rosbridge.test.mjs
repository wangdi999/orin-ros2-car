import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  ESTOP_TOPIC,
  MANUAL_CMD_TOPIC,
  RosbridgeClient,
  ROS2_TWIST_TYPE,
  TRIGGER_SERVICE_TYPE
} from './rosbridge.mjs';
import { telemetry } from './state.mjs';

test('manual drive publishes only to the arbiter input topic', () => {
  const sent = [];
  const client = new RosbridgeClient(() => ({ car: { host: '192.168.43.137' } }));
  client.ws = {
    readyState: 1,
    send(message) {
      sent.push(JSON.parse(message));
    }
  };

  const ok = client.publishTwist({
    linear: { x: 0.1, y: 0, z: 0 },
    angular: { x: 0, y: 0, z: 0 }
  });

  assert.equal(ok, true);
  assert.equal(sent.length, 1);
  assert.equal(sent[0].op, 'publish');
  assert.equal(sent[0].topic, MANUAL_CMD_TOPIC);
  assert.equal(sent[0].type, undefined);
});

test('manual command input is explicitly advertised before publishing', () => {
  const sent = [];
  const client = new RosbridgeClient(() => ({ car: { host: '192.168.43.137' } }));
  client.ws = {
    readyState: 1,
    send(message) {
      sent.push(JSON.parse(message));
    }
  };

  const ok = client.advertise(MANUAL_CMD_TOPIC, ROS2_TWIST_TYPE, 1);

  assert.equal(ok, true);
  assert.deepEqual(sent, [{
    op: 'advertise',
    topic: MANUAL_CMD_TOPIC,
    type: ROS2_TWIST_TYPE,
    queue_size: 1
  }]);
});

test('emergency stop latches safety and sends a manual zero without publishing /cmd_vel', () => {
  const sent = [];
  const client = new RosbridgeClient(() => ({ car: { host: '192.168.43.137' } }));
  client.connected = true;
  client.ws = {
    readyState: 1,
    send(message) {
      sent.push(JSON.parse(message));
    }
  };

  assert.equal(client.emergencyStop(1), true);
  assert.deepEqual(sent.map((item) => item.topic), [ESTOP_TOPIC, MANUAL_CMD_TOPIC]);
  assert.equal(sent.some((item) => item.topic === '/cmd_vel'), false);
  assert.equal(sent[0].msg.data, true);
  assert.equal(sent[1].msg.linear.x, 0);
});

test('Trigger service responses preserve rejection details', async () => {
  const sent = [];
  const client = new RosbridgeClient(() => ({ car: { host: '192.168.43.137' } }));
  client.connected = true;
  client.ws = {
    readyState: 1,
    send(message) {
      sent.push(JSON.parse(message));
    }
  };

  const responsePromise = client.callTrigger('/safety/reset');
  const request = sent.at(-1);
  assert.equal(request.op, 'call_service');
  assert.equal(request.service, '/safety/reset');
  assert.equal(request.type, TRIGGER_SERVICE_TYPE);

  client.handleMessage(JSON.stringify({
    op: 'service_response',
    id: request.id,
    service: request.service,
    result: true,
    values: { success: false, message: 'odometry is stale' }
  }));
  const response = await responsePromise;
  assert.equal(response.ok, true);
  assert.equal(response.success, false);
  assert.equal(response.message, 'odometry is stale');
});

test('legacy alarm JSON preserves the typed Alarm contract', () => {
  const client = new RosbridgeClient(() => ({ car: { host: '192.168.43.137' } }));
  let received = null;
  client.once('car-alarm', (alarm) => {
    received = alarm;
  });

  client.handleMessage(JSON.stringify({
    op: 'publish',
    topic: '/alarm_events',
    msg: {
      data: JSON.stringify({
        severity: 2,
        code: 'ODOM_TF_STALE',
        source: 'safety_manager',
        state: 'ODOM_TF_FAULT',
        message: 'odometry is stale',
        active: true
      })
    }
  }));

  assert.equal(received.type, 'ODOM_TF_STALE');
  assert.equal(received.severity, 'error');
  assert.equal(received.active, true);
  assert.equal(received.dedupeKey, 'safety_manager:ODOM_TF_STALE');
});

test('simulated low battery is an explicit Trigger service request', async () => {
  const sent = [];
  const client = new RosbridgeClient(() => ({ car: { host: '192.168.43.137' } }));
  client.connected = true;
  client.ws = {
    readyState: 1,
    send(message) {
      sent.push(JSON.parse(message));
    }
  };

  const responsePromise = client.callTrigger('/safety/simulate_low_battery');
  const request = sent.at(-1);
  assert.equal(request.service, '/safety/simulate_low_battery');
  client.handleMessage(JSON.stringify({
    op: 'service_response',
    id: request.id,
    result: true,
    values: { success: false, message: 'Home route is not configured' }
  }));
  const response = await responsePromise;
  assert.equal(response.success, false);
  assert.match(response.message, /Home route/);
});

test('pose resolution keeps the last trusted map pose when fresh sources disappear', () => {
  const client = new RosbridgeClient(() => ({ car: { host: '192.168.43.137' } }));
  telemetry.pose = {
    connected: true,
    frameId: 'map',
    childFrameId: 'base_footprint',
    source: 'amcl',
    pose: { x: 1.2, y: -0.4, yaw: 0.5 },
    updatedAt: '2026-07-13T08:00:00.000Z'
  };
  client.refreshGlobalPose('2026-07-13T08:00:10.000Z');
  assert.equal(telemetry.pose.connected, false);
  assert.equal(telemetry.pose.stale, true);
  assert.deepEqual(telemetry.pose.pose, { x: 1.2, y: -0.4, yaw: 0.5 });
});

test('closing rosbridge clears localization buffers before a host reconnect', () => {
  const client = new RosbridgeClient(() => ({ car: { host: '192.168.43.137' } }));
  client.tfBuffer.update({ transforms: [{
    header: { frame_id: 'map' }, child_frame_id: 'base_footprint',
    transform: { translation: { x: 1, y: 2 }, rotation: { z: 0, w: 1 } }
  }] });
  assert.equal(client.tfBuffer.resolve('map', 'base_footprint').connected, true);
  client.close();
  assert.equal(client.tfBuffer.resolve('map', 'base_footprint').connected, false);
});
