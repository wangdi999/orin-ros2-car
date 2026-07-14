import assert from 'node:assert/strict';
import { test } from 'node:test';
import { parsePointCloud2 } from './pointCloud.mjs';
import { remotePerceptionStatusScript } from './perceptionManager.mjs';
import { buildRosbagRecordCommand, buildTrackingRemapArguments } from './recordingManager.mjs';
import { discoverPerceptionTopics, parseTopicListTypes } from './topicDiscovery.mjs';

test('topic discovery matches Astra RGB, depth, IR, PointCloud2, and tracking topics', () => {
  const topics = parseTopicListTypes(`
/camera/color/image_raw [sensor_msgs/msg/Image]
/camera/depth/image_raw [sensor_msgs/msg/Image]
/camera/ir/image_raw [sensor_msgs/msg/Image]
/camera/depth/points [sensor_msgs/msg/PointCloud2]
/tracking_cmd_vel_shadow [geometry_msgs/msg/Twist]
`);
  const discovery = discoverPerceptionTopics(topics);

  assert.equal(discovery.matches.camera.topic, '/camera/color/image_raw');
  assert.equal(discovery.matches.depth.topic, '/camera/depth/image_raw');
  assert.equal(discovery.matches.ir.topic, '/camera/ir/image_raw');
  assert.equal(discovery.matches.pointCloud.topic, '/camera/depth/points');
  assert.equal(discovery.matches.trackingVelocity.topic, '/tracking_cmd_vel_shadow');
  assert.equal(discovery.matches.camera.type, 'sensor_msgs/msg/Image');
});

test('topic discovery prefers compressed RGB preview when available', () => {
  const topics = parseTopicListTypes(`
/camera/color/image_raw [sensor_msgs/msg/Image]
/camera/color/image_raw/compressed [sensor_msgs/msg/CompressedImage]
`);
  const discovery = discoverPerceptionTopics(topics);
  assert.equal(discovery.matches.camera.topic, '/camera/color/image_raw/compressed');
});

test('tracking remap arguments isolate both relative and absolute cmd_vel outputs', () => {
  assert.deepEqual(buildTrackingRemapArguments(), [
    '--ros-args',
    '-r',
    'cmd_vel:=/tracking_cmd_vel_shadow',
    '-r',
    '/cmd_vel:=/tracking_cmd_vel_shadow'
  ]);
});

test('tracking velocity discovery does not fall back to unrelated Twist topics', () => {
  const topics = parseTopicListTypes(`
/vel_raw [geometry_msgs/msg/Twist]
/cmd_vel [geometry_msgs/msg/Twist]
`);
  const discovery = discoverPerceptionTopics(topics);
  assert.equal(discovery.matches.trackingVelocity.topic, null);
  assert.equal(discovery.matches.trackingVelocity.matched, false);
});

test('rosbag command records selected topics without publishing real cmd_vel', () => {
  const command = buildRosbagRecordCommand('bag-test', ['/scan', '/tracking_cmd_vel_shadow', '/cmd_vel']);
  assert.match(command, /ros2 bag record/);
  assert.match(command, /\/scan/);
  assert.match(command, /\/tracking_cmd_vel_shadow/);
  assert.match(command, /\/cmd_vel/);
  assert.doesNotMatch(command, /topic pub/);
});

test('PointCloud2 parser samples coordinates and packed RGB colors', () => {
  const pointStep = 16;
  const buffer = Buffer.alloc(pointStep * 3);
  const colors = [0xff0000, 0x00ff00, 0x0000ff];
  for (let index = 0; index < 3; index += 1) {
    const base = index * pointStep;
    buffer.writeFloatLE(index + 1, base);
    buffer.writeFloatLE(index + 2, base + 4);
    buffer.writeFloatLE(index + 3, base + 8);
    buffer.writeUInt32LE(colors[index], base + 12);
  }

  const parsed = parsePointCloud2({
    header: { frame_id: 'camera_depth_optical_frame' },
    width: 3,
    height: 1,
    is_bigendian: false,
    point_step: pointStep,
    fields: [
      { name: 'x', offset: 0 },
      { name: 'y', offset: 4 },
      { name: 'z', offset: 8 },
      { name: 'rgb', offset: 12 }
    ],
    data: buffer.toString('base64')
  }, { maxPoints: 2 });

  assert.equal(parsed.connected, true);
  assert.equal(parsed.totalPoints, 3);
  assert.equal(parsed.points.length, 2);
  assert.deepEqual(parsed.points[0], { x: 1, y: 2, z: 3, color: '#ff0000' });
  assert.equal(parsed.bounds.minX, 1);
});

test('perception status discovery does not auto-start the ROS2 CLI daemon', () => {
  const script = remotePerceptionStatusScript();
  assert.match(script, /ros2 topic list --no-daemon -t/);
  assert.doesNotMatch(script, /ros2 (run|launch|topic pub|service call|action send_goal)/);
});
