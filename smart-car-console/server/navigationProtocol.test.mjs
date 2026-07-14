import assert from 'node:assert/strict';
import test from 'node:test';
import {
  INITIAL_POSE_TYPE,
  NAVIGATE_POSE_SERVICE_TYPE,
  buildInitialPoseMessage,
  normalizeMapId,
  validateRoute,
  worldFromCanvas
} from './navigationProtocol.mjs';

test('map identifiers reject path and shell injection', () => {
  assert.equal(normalizeMapId('campus_map-2'), 'campus_map-2');
  for (const invalid of ['../map', 'map;rm', '/root/map', 'a b', '', 'a'.repeat(65)]) {
    assert.throws(() => normalizeMapId(invalid), /Map name/);
  }
});

test('route validation keeps the fixed Home plus three-waypoint contract', () => {
  const route = validateRoute({
    configured: true,
    frame_id: 'map',
    home: { name: 'home', x: 0, y: 0, yaw: 0 },
    waypoints: [
      { name: 'a', x: 1, y: 0, yaw: 0 },
      { name: 'b', x: 1, y: 1, yaw: 1.57, dwell_sec: 2 },
      { name: 'c', x: 0, y: 1, yaw: 3.14 }
    ],
    default_dwell_sec: 3,
    max_retries: 1,
    failure_policy: 'skip',
    loop: false
  });
  assert.equal(route.waypoints.length, 3);
  assert.equal(route.frame_id, 'map');
  assert.throws(() => validateRoute({ ...route, waypoints: route.waypoints.slice(0, 2) }), /three/);
});

test('initial pose uses map frame and fixed covariance', () => {
  assert.equal(INITIAL_POSE_TYPE, 'geometry_msgs/PoseWithCovarianceStamped');
  assert.equal(NAVIGATE_POSE_SERVICE_TYPE, 'car_interfaces/srv/NavigatePose');
  const message = buildInitialPoseMessage({ x: 1.5, y: -2, yaw: Math.PI / 2 }, 1234);
  assert.equal(message.header.frame_id, 'map');
  assert.equal(message.pose.pose.position.x, 1.5);
  assert.equal(message.pose.covariance[0], 0.25);
  assert.equal(message.pose.covariance[7], 0.25);
  assert.equal(message.pose.covariance[35], 0.0685);
});

test('canvas inverse projection returns map coordinates', () => {
  const point = worldFromCanvas({
    clientX: 60,
    clientY: 40,
    rect: { left: 10, top: 20 },
    projection: { scale: 10, offsetX: 20, offsetY: 30 }
  });
  assert.deepEqual(point, { x: 3, y: 1 });
});

test('poses and configured routes reject blank coordinates instead of coercing them to zero', () => {
  for (const value of [null, '', '   ']) {
    assert.throws(() => buildInitialPoseMessage({ x: value, y: 0, yaw: 0 }), /finite/);
  }
  assert.throws(() => validateRoute({
    configured: true,
    frame_id: 'map',
    home: { name: 'home', x: null, y: 0, yaw: 0 },
    waypoints: [
      { name: 'a', x: 1, y: 0, yaw: 0 },
      { name: 'b', x: 1, y: 1, yaw: 1 },
      { name: 'c', x: 0, y: 1, yaw: 2 }
    ],
    default_dwell_sec: 0,
    max_retries: 1,
    failure_policy: 'skip',
    loop: false
  }), /home\.x must be finite/);
});
