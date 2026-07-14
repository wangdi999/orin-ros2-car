import assert from 'node:assert/strict';
import test from 'node:test';
import { NavigationWorkspaceManager } from './navigationWorkspace.mjs';

function manager(options = {}) {
  const { initialConfig, ...overrides } = options;
  const calls = [];
  let config = initialConfig ?? {
    navigation: { mode: 'safe_base', map: '/root/maps/campus_map.yaml', routeFile: '/root/routes/campus_map.yaml' },
    safety: { motionWarningAcknowledgedAt: null }
  };
  const instance = new NavigationWorkspaceManager({
    ssh: { run: async () => ({ ok: true, stdout: '', stderr: '' }) },
    rosbridge: {
      connected: true,
      stopManual: () => calls.push('zero'),
      callTrigger: async (service) => { calls.push(service); return { ok: true, success: true }; }
    },
    serviceManager: {
      stopServices: async () => { calls.push('stop'); return { ok: true }; },
      startServices: async () => { calls.push('start'); return { ok: true }; }
    },
    getConfig: () => config,
    saveConfig: async (next) => { config = next; calls.push(`save:${next.navigation.mode}`); },
    getRuntime: () => ({ navigation: { goal: { state: 'IDLE' } } }),
    getTelemetry: () => ({ map: { connected: true } }),
    ...overrides
  });
  return { instance, calls, getConfig: () => config };
}

test('mode switch cancels and zeros before stopping and starting services', async () => {
  const { instance, calls, getConfig } = manager();
  const operation = instance.startModeSwitch('mapping');
  await instance.waitForOperation(operation.operationId);
  assert.deepEqual(calls, ['/navigation/cancel', 'zero', 'stop', 'save:mapping', 'start']);
  assert.equal(getConfig().navigation.mode, 'mapping');
  assert.equal(instance.currentOperation().status, 'SUCCEEDED');
});

test('workflow rejects concurrent long operations', async () => {
  let release;
  const blocked = new Promise((resolve) => { release = resolve; });
  const { instance } = manager({
    serviceManager: {
      stopServices: async () => { await blocked; return { ok: true }; },
      startServices: async () => ({ ok: true })
    }
  });
  instance.startModeSwitch('mapping');
  assert.throws(() => instance.startModeSwitch('navigation'), /already running/);
  assert.throws(() => instance.assertMotionStartAllowed(), /already running/);
  release();
});

test('motion warning acknowledgement is required only for motion starts', async () => {
  const { instance } = manager();
  assert.throws(() => instance.assertMotionAcknowledged(), /acknowledge/i);
  await instance.setMotionWarningAcknowledged(true);
  assert.doesNotThrow(() => instance.assertMotionAcknowledged());
  await instance.setMotionWarningAcknowledged(false);
  assert.throws(() => instance.assertMotionAcknowledged(), /acknowledge/i);
});

test('non-navigation modes allow idle map edits without a navigation status heartbeat', () => {
  const { instance } = manager({
    getRuntime: () => ({ navigation: { goal: { state: 'UNKNOWN' } } })
  });
  assert.doesNotThrow(() => instance.assertNavigationIdle());
});

test('running navigation requires a terminal coordinator state and cannot hot-swap maps', async () => {
  const { instance } = manager({
    initialConfig: {
      navigation: { mode: 'navigation', map: '/root/maps/campus_map.yaml', routeFile: '/root/routes/campus_map.yaml' },
      safety: { motionWarningAcknowledgedAt: '2026-07-14T00:00:00.000Z' }
    },
    getRuntime: () => ({ navigation: { goal: { state: 'UNKNOWN' } } })
  });
  assert.throws(() => instance.assertNavigationIdle(), /active/);
  await assert.rejects(() => instance.activateMap('next_map'), /Switch to safe_base or mapping/);
});

test('route save accepts the fixed contract and skips reload outside navigation mode', async () => {
  const remoteScripts = [];
  const { instance, calls } = manager({
    ssh: {
      run: async (command) => {
        remoteScripts.push(command.script);
        return { ok: true, stdout: '', stderr: '' };
      }
    },
    getRuntime: () => ({ navigation: { goal: { state: 'UNKNOWN' } } })
  });
  const saved = await instance.saveRoute('campus_map', {
    configured: true,
    frame_id: 'map',
    home: { name: 'Home', x: 0, y: 0, yaw: 0 },
    waypoints: [
      { name: 'A', x: 1, y: 0, yaw: 0 },
      { name: 'B', x: 1, y: 1, yaw: 1 },
      { name: 'C', x: 0, y: 1, yaw: 2 }
    ],
    default_dwell_sec: 0,
    max_retries: 1,
    failure_policy: 'skip',
    loop: false
  });
  assert.equal(saved.waypoints.length, 3);
  assert.equal(remoteScripts.length, 1);
  assert.equal(calls.includes('/patrol/reload_route'), false);
});

test('P5 preview preserves a low-valued first pixel after the header separator', async () => {
  const pgm = Buffer.concat([Buffer.from('P5\n1 1\n255\n', 'ascii'), Buffer.from([0])]);
  const yaml = Buffer.from('image: test_map.pgm\nresolution: 0.05\norigin: [0, 0, 0]\n', 'utf8');
  const { instance } = manager({
    ssh: {
      run: async (command) => ({
        ok: true,
        stdout: command.script.includes('.pgm') ? pgm.toString('base64') : yaml.toString('base64'),
        stderr: ''
      })
    }
  });
  const preview = await instance.getMapPreview('test_map');
  assert.deepEqual(preview.pixels, [[0]]);
});

test('single goals require a managed active map', async () => {
  const { instance } = manager({
    initialConfig: {
      navigation: {
        mode: 'navigation',
        map: '/root/ros2_navigation_overlay/install/share/icar_navigation/maps/campus_map.yaml',
        routeFile: '/root/ros2_navigation_overlay/install/share/icar_navigation/config/patrol_route.yaml'
      },
      safety: { motionWarningAcknowledgedAt: '2026-07-14T00:00:00.000Z' }
    },
    getTelemetry: () => ({ pose: { connected: true, stale: false } })
  });
  await assert.rejects(() => instance.sendGoal({ x: 1, y: 1, yaw: 0 }), /managed map/);
});
