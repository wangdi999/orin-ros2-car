import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  ESTOP_TOPIC,
  MANUAL_CMD_TOPIC,
  RosbridgeClient,
  ROS2_TWIST_TYPE,
  TRIGGER_SERVICE_TYPE
} from './rosbridge.mjs';
import { INITIAL_POSE_TOPIC, NAVIGATE_POSE_SERVICE } from './navigationProtocol.mjs';
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

test('perception streams subscribe only while preview is enabled and use the preview limits', () => {
  const sent = [];
  const client = new RosbridgeClient(() => ({ car: { host: '192.168.43.137' } }));
  client.connected = true;
  client.ws = { readyState: 1, send: (message) => sent.push(JSON.parse(message)) };
  client.setPerceptionSubscriptions({
    color: { role: 'camera', topic: '/camera/color/image_raw', type: 'sensor_msgs/msg/Image' },
    cloud: { role: 'pointCloud', topic: '/camera/depth/points', type: 'sensor_msgs/msg/PointCloud2' }
  });
  assert.equal(sent.length, 0);

  client.setPerceptionPreviewEnabled(true);
  const subscriptions = sent.filter((item) => item.op === 'subscribe');
  assert.deepEqual(subscriptions.map((item) => [item.topic, item.throttle_rate, item.queue_length]), [
    ['/camera/color/image_raw', 200, 1],
    ['/camera/depth/points', 500, 1]
  ]);

  client.setPerceptionPreviewEnabled(false);
  assert.deepEqual(sent.filter((item) => item.op === 'unsubscribe').map((item) => item.topic), [
    '/camera/color/image_raw', '/camera/depth/points'
  ]);
});

test('perception topic discovery removes obsolete subscriptions while preview is enabled', () => {
  const sent = [];
  const client = new RosbridgeClient(() => ({ car: { host: '192.168.43.137' } }));
  client.connected = true;
  client.ws = { readyState: 1, send: (message) => sent.push(JSON.parse(message)) };
  client.setPerceptionPreviewEnabled(true);
  client.setPerceptionSubscriptions({
    old: { role: 'camera', topic: '/old/image', type: 'sensor_msgs/msg/Image' }
  });
  client.setPerceptionSubscriptions({
    next: { role: 'camera', topic: '/next/image', type: 'sensor_msgs/msg/Image' }
  });

  assert.deepEqual(sent.map((item) => [item.op, item.topic]), [
    ['subscribe', '/old/image'],
    ['unsubscribe', '/old/image'],
    ['subscribe', '/next/image']
  ]);
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

test('initial pose publishes only the standard map-frame localization topic', () => {
  const sent = [];
  const client = new RosbridgeClient(() => ({ car: { host: '192.168.43.137' } }));
  client.ws = { readyState: 1, send: (message) => sent.push(JSON.parse(message)) };
  assert.equal(client.publishInitialPose({ x: 1, y: 2, yaw: 0.5 }), true);
  assert.equal(sent[0].topic, INITIAL_POSE_TOPIC);
  assert.equal(sent[0].msg.header.frame_id, 'map');
  assert.equal(sent[0].msg.pose.covariance[35], 0.0685);
});

test('single navigation goal uses the typed coordinator service', async () => {
  const sent = [];
  const client = new RosbridgeClient(() => ({ car: { host: '192.168.43.137' } }));
  client.connected = true;
  client.ws = { readyState: 1, send: (message) => sent.push(JSON.parse(message)) };
  const pending = client.sendNavigationGoal({ x: 1, y: 2, yaw: 0.5 });
  const request = sent.at(-1);
  assert.equal(request.service, NAVIGATE_POSE_SERVICE);
  assert.deepEqual(request.args, { x: 1, y: 2, yaw: 0.5 });
  client.handleMessage(JSON.stringify({
    op: 'service_response', id: request.id, result: true,
    values: { accepted: true, goal_id: 'web-1', message: 'single goal accepted' }
  }));
  const response = await pending;
  assert.equal(response.success, true);
  assert.equal(response.values.goal_id, 'web-1');
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
