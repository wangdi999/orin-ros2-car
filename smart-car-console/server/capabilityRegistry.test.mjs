import assert from 'node:assert/strict';
import { mkdtemp, readFile, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import test from 'node:test';
import {
  CAPABILITY_DEFINITIONS,
  CapabilityManager,
  buildReadonlyCapabilityProbeScript,
  evaluateCapabilities,
  sanitizeCapabilityEvidence
} from './capabilityRegistry.mjs';

const NOW = '2026-07-13T08:00:00.000Z';

function evidence(overrides = {}) {
  const { hardware: hardwareOverrides = {}, ros: rosOverrides = {}, ...rootOverrides } = overrides;
  return {
    probeOk: true,
    complete: true,
    detectedAt: NOW,
    hardware: {
      devicePaths: ['/dev/rplidar', '/dev/ttyUSB0', '/dev/video0', '/dev/video1'],
      usbIds: ['2bc5:060f', '2bc5:050f'],
      ...hardwareOverrides
    },
    ros: {
      container: 'smartcar_icar_console',
      containerRunning: true,
      packagesInspectable: true,
      packages: ['icar_astra', 'astra_camera', 'icar_bringup', 'icar_navigation'],
      executables: ['icar_bringup/Mcnamu_driver_X3', 'icar_astra/colorTracker'],
      nodes: ['/Mcnamu_driver_X3'],
      topics: ['/odom', '/imu/data_raw', '/voltage'],
      ...rosOverrides
    },
    error: null,
    ...rootOverrides
  };
}

test('ORBBEC hardware is supported by USB identity and video nodes without Astra symlinks', () => {
  const result = evaluateCapabilities(evidence(), null, { now: NOW });

  assert.equal(result.items.rgb_camera.availability, 'SUPPORTED');
  assert.equal(result.items.depth_ir.availability, 'SUPPORTED');
  assert.match(result.items.depth_ir.evidence.hardware.join(' '), /2bc5:060f/);
});

test('registry contains X3 definitions and excludes R2/X1 variants', () => {
  const serialized = JSON.stringify(CAPABILITY_DEFINITIONS);

  assert.match(serialized, /Mcnamu_driver_X3/);
  assert.doesNotMatch(serialized, /Mcnamu_driver_R2|Mcnamu_driver_X1/);
});

test('stopped ROS container preserves cached support and reports stale instead of unsupported', () => {
  const previous = evaluateCapabilities(evidence(), null, { now: NOW });
  const stoppedAt = '2026-07-13T08:05:00.000Z';
  const stopped = evidence({
    detectedAt: stoppedAt,
    complete: false,
    ros: {
      container: 'smartcar_icar_console',
      containerRunning: false,
      packagesInspectable: false,
      packages: [],
      executables: [],
      nodes: [],
      topics: []
    }
  });

  const result = evaluateCapabilities(stopped, previous, { now: stoppedAt });

  assert.equal(result.items.safe_base.availability, 'SUPPORTED');
  assert.equal(result.items.safe_base.runtime, 'STALE');
  assert.match(result.items.safe_base.reason, /容器.*停止|缓存|过期/);
});

test('fresh complete package evidence can explicitly mark a missing X3 capability unsupported', () => {
  const result = evaluateCapabilities(evidence({
    ros: {
      containerRunning: true,
      packagesInspectable: true,
      packages: ['icar_bringup'],
      executables: ['icar_bringup/Mcnamu_driver_X3'],
      nodes: [],
      topics: []
    }
  }), null, { now: NOW });

  assert.equal(result.items.mapping.availability, 'UNSUPPORTED');
  assert.equal(result.items.safe_base.availability, 'SUPPORTED');
});

test('generic laser package and /scan do not prove vendor algorithms are installed or active', () => {
  const result = evaluateCapabilities(evidence({
    ros: {
      packages: ['icar_bringup', 'icar_laser'],
      executables: ['icar_bringup/Mcnamu_driver_X3'],
      nodes: ['/sllidar_node'],
      topics: ['/scan']
    }
  }), null, { now: NOW });
  assert.equal(result.items.laser_avoidance.availability, 'UNSUPPORTED');
  assert.equal(result.items.laser_avoidance.runtime, 'INACTIVE');
});

test('generic video devices alone do not prove depth or infrared support', () => {
  const result = evaluateCapabilities(evidence({
    hardware: { devicePaths: ['/dev/video0'], usbIds: [] },
    ros: { packages: [], executables: [], nodes: [], topics: [] }
  }), null, { now: NOW });
  assert.equal(result.items.rgb_camera.availability, 'SUPPORTED');
  assert.equal(result.items.depth_ir.availability, 'UNSUPPORTED');
});

test('runtime state requires feature-specific nodes and topics, not any partial graph match', () => {
  const result = evaluateCapabilities(evidence({
    ros: {
      packages: ['icar_bringup', 'icar_navigation'],
      executables: ['icar_bringup/Mcnamu_driver_X3'],
      nodes: ['/Mcnamu_driver_X3'],
      topics: ['/odom']
    }
  }), null, { now: NOW });
  assert.equal(result.items.safe_base.availability, 'SUPPORTED');
  assert.equal(result.items.safe_base.runtime, 'INACTIVE');
});

test('a partial Nav2 package set does not prove the complete localization stack', () => {
  const result = evaluateCapabilities(evidence({
    ros: { packages: ['nav2_amcl'], executables: [], nodes: [], topics: [] }
  }), null, { now: NOW });
  assert.equal(result.items.localization_navigation.availability, 'UNSUPPORTED');
});

test('vendor motion demonstrations are always blocked from web activation', () => {
  const result = evaluateCapabilities(evidence({
    ros: {
      packages: ['icar_bringup', 'icar_laser', 'icar_linefollow'],
      executables: [
        'icar_bringup/Mcnamu_driver_X3',
        'icar_laser/laser_Avoidance_X3',
        'icar_linefollow/linefollow_X3'
      ],
      nodes: ['/laser_Avoidance_X3'],
      topics: ['/scan']
    }
  }), null, { now: NOW });

  for (const key of ['laser_avoidance', 'line_follow']) {
    assert.equal(result.items[key].safety, 'BLOCKED');
    assert.equal(result.items[key].blockedReason, '未接入 `/cmd_vel` 唯一安全仲裁，网页不可启动');
  }
});

test('probe failures recover cached evidence and never write secrets or serial numbers', async () => {
  const cacheDir = await mkdtemp(path.join(tmpdir(), 'smart-car-capabilities-'));
  const cachePath = path.join(cacheDir, 'capability-cache.json');
  const secret = 'not-for-cache';
  const logs = [];
  let calls = 0;
  const manager = new CapabilityManager({
    ssh: {
      async run() {
        calls += 1;
        if (calls === 1) {
          return { ok: true, stdout: JSON.stringify(evidence({
            hardware: { serialNumbers: ['SERIAL-PRIVATE-123'] }
          })), stderr: '' };
        }
        return { ok: false, stdout: '', stderr: `SSH failed with ${secret}`, code: 255 };
      }
    },
    cachePath,
    logger: (_level, _scope, message, detail) => logs.push({ message, detail })
  });

  const fresh = await manager.refresh({ now: NOW });
  const recovered = await manager.refresh({ now: '2026-07-13T08:06:00.000Z' });
  const cacheText = await readFile(cachePath, 'utf8');
  const publicText = JSON.stringify(recovered);
  const logText = JSON.stringify(logs);

  assert.equal(fresh.items.depth_ir.availability, 'SUPPORTED');
  assert.equal(recovered.items.depth_ir.availability, 'SUPPORTED');
  assert.equal(recovered.stale, true);
  for (const text of [cacheText, publicText, logText]) {
    assert.doesNotMatch(text, /not-for-cache|SERIAL-PRIVATE-123|sshPassword|hostKey|token/i);
  }
});

test('tampered legacy cache is whitelisted before reuse or persistence', async () => {
  const cacheDir = await mkdtemp(path.join(tmpdir(), 'smart-car-capabilities-tampered-'));
  const cachePath = path.join(cacheDir, 'capability-cache.json');
  const cached = evaluateCapabilities(evidence(), null, { now: NOW });
  cached.evidence.password = 'CACHE-SECRET';
  cached.evidence.ros.hostKey = 'SHA256:CACHE-SECRET';
  cached.items.safe_base.reason = 'token=CACHE-SECRET';
  cached.items.safe_base.evidence.secret = 'CACHE-SECRET';
  cached.items.safe_base.evidence.nodes.push('token=CACHE-SECRET');
  await writeFile(cachePath, JSON.stringify(cached), 'utf8');
  const manager = new CapabilityManager({
    ssh: { async run() { return { ok: false, stdout: '', stderr: 'unavailable', code: 255 }; } },
    cachePath
  });

  const result = await manager.refresh({ now: '2026-07-13T08:10:00.000Z' });
  const persisted = await readFile(cachePath, 'utf8');
  assert.doesNotMatch(JSON.stringify(result), /CACHE-SECRET|hostKey|password|token=/i);
  assert.doesNotMatch(persisted, /CACHE-SECRET|hostKey|password|token=/i);
});

test('concurrent capability refreshes share one read-only probe', async () => {
  const cacheDir = await mkdtemp(path.join(tmpdir(), 'smart-car-capabilities-singleflight-'));
  let calls = 0;
  const manager = new CapabilityManager({
    ssh: {
      async run() {
        calls += 1;
        await new Promise((resolve) => setImmediate(resolve));
        return { ok: true, stdout: JSON.stringify(evidence()), stderr: '' };
      }
    },
    cachePath: path.join(cacheDir, 'capability-cache.json'),
    minRefreshMs: 0
  });
  await Promise.all([manager.refresh({ force: true, now: NOW }), manager.refresh({ force: true, now: NOW })]);
  assert.equal(calls, 1);
});

test('evidence sanitizer keeps useful device and ROS facts while dropping sensitive fields', () => {
  const clean = sanitizeCapabilityEvidence({
    detectedAt: NOW,
    hardware: {
      devicePaths: ['/dev/video0'],
      usbIds: ['2bc5:060f'],
      serialNumbers: ['private']
    },
    ros: { packages: ['astra_camera'], nodes: ['/astra_camera'], topics: ['/camera/depth/image_raw'] },
    sshPassword: 'private',
    token: 'private'
  });

  assert.deepEqual(clean.hardware.devicePaths, ['/dev/video0']);
  assert.deepEqual(clean.hardware.usbIds, ['2bc5:060f']);
  assert.equal(clean.hardware.serialNumbers, undefined);
  assert.equal(clean.sshPassword, undefined);
  assert.equal(clean.token, undefined);
});

test('read-only probe script contains no state-changing ROS, Docker or service commands', () => {
  const script = buildReadonlyCapabilityProbeScript();

  assert.match(script, /docker ps/);
  assert.match(script, /ros2 (pkg|node|topic)/);
  assert.match(script, /ros2 node list --no-daemon/);
  assert.match(script, /ros2 topic list --no-daemon/);
  assert.match(script, /echo "EXECUTABLE\|\$package\/\$executable"/);
  assert.doesNotMatch(script, /awk/);
  assert.doesNotMatch(script, /docker (start|restart|run|rm)|ros2 (run|launch|topic pub|service call|action send_goal)|systemctl (start|restart|stop)/);
  assert.match(script, /probe_rc/);
  assert.doesNotMatch(script, /fi\s*echo 'COMPLETE\|1'\s*`?$/);
});
