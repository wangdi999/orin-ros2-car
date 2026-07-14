import assert from 'node:assert/strict';
import test from 'node:test';
import {
  Tf2dBuffer,
  parseOccupancyGrid,
  parseOdometry,
  parsePath,
  parsePoseWithCovariance,
  resolveMapPose,
  withFreshness
} from './mapTelemetry.mjs';

test('OccupancyGrid parser downsamples map metadata and cells', () => {
  const map = parseOccupancyGrid({
    header: { frame_id: 'map' },
    info: {
      width: 4,
      height: 2,
      resolution: 0.05,
      origin: {
        position: { x: -1, y: -2 },
        orientation: { z: 0, w: 1 }
      }
    },
    data: [-1, 0, 50, 100, 20, 80, -1, 0]
  });

  assert.equal(map.connected, true);
  assert.equal(map.mode, 'map');
  assert.equal(map.frameId, 'map');
  assert.equal(map.width, 4);
  assert.equal(map.height, 2);
  assert.equal(map.resolution, 0.05);
  assert.deepEqual(map.origin, { x: -1, y: -2, yaw: 0 });
  assert.deepEqual(map.cells, [-1, 0, 50, 100, 20, 80, -1, 0]);
  assert.equal(map.occupied, 2);
  assert.equal(map.unknown, 2);
});

test('OccupancyGrid rejects truncated data and max-pools occupied cells when downsampling', () => {
  const invalid = parseOccupancyGrid({
    info: {
      width: 2, height: 2, resolution: 0.05,
      origin: { position: { x: 0, y: 0 }, orientation: { z: 0, w: 1 } }
    },
    data: [0, 0, 0]
  });
  assert.equal(invalid.connected, false);

  const width = 262;
  const data = Array(width).fill(-1);
  data[1] = 100;
  const pooled = parseOccupancyGrid({
    header: { frame_id: 'map' },
    info: {
      width, height: 1, resolution: 0.05,
      origin: { position: { x: 0, y: 0 }, orientation: { z: 0, w: 1 } }
    },
    data
  });
  assert.equal(pooled.step, 2);
  assert.equal(pooled.cells[0], 100);
});

test('Odometry parser extracts 2D pose and yaw', () => {
  const odom = parseOdometry({
    header: { frame_id: 'odom' },
    child_frame_id: 'base_footprint',
    pose: {
      pose: {
        position: { x: 1.25, y: -0.5 },
        orientation: { z: Math.sin(Math.PI / 4), w: Math.cos(Math.PI / 4) }
      }
    },
    twist: { twist: { linear: { x: 0.1 }, angular: { z: -0.2 } } }
  });

  assert.equal(odom.connected, true);
  assert.equal(odom.frameId, 'odom');
  assert.equal(odom.childFrameId, 'base_footprint');
  assert.equal(odom.pose.x, 1.25);
  assert.equal(odom.pose.y, -0.5);
  assert.equal(odom.pose.yaw, 1.5708);
  assert.equal(odom.linear, 0.1);
  assert.equal(odom.angular, -0.2);
});

test('TF buffer composes map -> odom -> base_footprint in 2D', () => {
  const tf = new Tf2dBuffer();
  tf.update({ transforms: [
    {
      header: { frame_id: 'map' },
      child_frame_id: 'odom',
      transform: {
        translation: { x: 1, y: 2 },
        rotation: { z: Math.sin(Math.PI / 4), w: Math.cos(Math.PI / 4) }
      }
    },
    {
      header: { frame_id: 'odom' },
      child_frame_id: 'base_footprint',
      transform: {
        translation: { x: 1, y: 0 },
        rotation: { z: 0, w: 1 }
      }
    }
  ] }, '2026-07-13T08:00:00.000Z');

  const pose = tf.resolve('map', 'base_footprint');

  assert.equal(pose.connected, true);
  assert.equal(pose.source, 'tf');
  assert.deepEqual(pose.pose, { x: 1, y: 3, yaw: 1.5708 });
});

test('TF buffer resolves inverse multi-edge chains and timestamps them by the oldest dynamic edge', () => {
  const tf = new Tf2dBuffer();
  tf.update({ transforms: [{
    header: { frame_id: 'map' }, child_frame_id: 'localization',
    transform: { translation: { x: 1, y: 0 }, rotation: { z: 0, w: 1 } }
  }] }, '2026-07-13T08:00:00.000Z');
  tf.update({ transforms: [{
    header: { frame_id: 'localization' }, child_frame_id: 'odom',
    transform: { translation: { x: 2, y: 0 }, rotation: { z: 0, w: 1 } }
  }] }, '2026-07-13T08:00:04.000Z', true);
  tf.update({ transforms: [{
    header: { frame_id: 'odom' }, child_frame_id: 'base_footprint',
    transform: { translation: { x: 3, y: 0 }, rotation: { z: 0, w: 1 } }
  }] }, '2026-07-13T08:00:05.000Z');

  const forward = tf.resolve('map', 'base_footprint');
  const inverse = tf.resolve('base_footprint', 'map');
  assert.equal(forward.connected, true);
  assert.equal(forward.pose.x, 6);
  assert.equal(forward.updatedAt, '2026-07-13T08:00:00.000Z');
  assert.equal(inverse.connected, true);
  assert.equal(inverse.pose.x, -6);
  assert.equal(resolveMapPose({ tfPose: forward }, '2026-07-13T08:00:05.001Z').connected, false);
});

test('fresh AMCL pose wins over TF and odometry; stale AMCL falls back to TF', () => {
  const amcl = {
    ...parsePoseWithCovariance({
      header: { frame_id: 'map' },
      pose: { pose: { position: { x: 9, y: 8 }, orientation: { z: 0, w: 1 } } }
    }),
    updatedAt: '2026-07-13T08:00:04.000Z'
  };
  const tfPose = {
    connected: true,
    frameId: 'map',
    childFrameId: 'base_footprint',
    source: 'tf',
    pose: { x: 2, y: 3, yaw: 0.5 },
    updatedAt: '2026-07-13T08:00:05.000Z'
  };
  const odom = {
    connected: true,
    frameId: 'odom',
    pose: { x: 1, y: 1, yaw: 0 },
    updatedAt: '2026-07-13T08:00:04.000Z'
  };

  assert.equal(resolveMapPose({ amcl, tfPose, odom }, '2026-07-13T08:00:05.000Z').source, 'amcl');
  assert.equal(resolveMapPose({ amcl, tfPose, odom }, '2026-07-13T08:00:09.001Z').source, 'tf');
});

test('Path parser retains endpoints while bounding browser payload size', () => {
  const path = parsePath({
    header: { frame_id: 'map' },
    poses: Array.from({ length: 700 }, (_, index) => ({
      pose: {
        position: { x: index / 10, y: index / 20 },
        orientation: { z: 0, w: 1 }
      }
    }))
  });

  assert.equal(path.connected, true);
  assert.equal(path.frameId, 'map');
  assert.equal(path.totalPoints, 700);
  assert.ok(path.points.length <= 260);
  assert.equal(path.points[0].x, 0);
  assert.equal(path.points.at(-1).x, 69.9);
});

test('Path parser drops invalid and frame-mismatched points instead of drawing them at zero', () => {
  const path = parsePath({
    header: { frame_id: 'map' },
    poses: [
      { header: { frame_id: 'map' }, pose: { position: { x: 1, y: 2 }, orientation: { z: 0, w: 1 } } },
      { header: { frame_id: 'odom' }, pose: { position: { x: 3, y: 4 }, orientation: { z: 0, w: 1 } } },
      { header: { frame_id: 'map' }, pose: { position: {}, orientation: { z: 0, w: 1 } } }
    ]
  });
  assert.equal(path.totalPoints, 3);
  assert.equal(path.invalidPoints, 2);
  assert.deepEqual(path.points, [{ x: 1, y: 2, yaw: 0 }]);
});

test('freshness marks five-second-old real data stale without deleting the last sample', () => {
  const sample = withFreshness({
    connected: true,
    points: [{ x: 1, y: 2 }],
    updatedAt: '2026-07-13T08:00:00.000Z'
  }, '2026-07-13T08:00:05.001Z');

  assert.equal(sample.stale, true);
  assert.equal(sample.ageMs, 5001);
  assert.deepEqual(sample.points, [{ x: 1, y: 2 }]);
  assert.match(sample.disconnectedReason, /5 秒/);
});
