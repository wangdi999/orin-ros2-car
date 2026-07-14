import assert from 'node:assert/strict';
import { test } from 'node:test';
import { buildRemoteStartScript, ServiceManager } from './serviceManager.mjs';
import {
  runtime,
  snapshot,
  updateNavigation,
  updateRosbridge,
  updateStatus
} from './state.mjs';

test('failed status refresh clears stale remote Docker and service state', async () => {
  updateStatus({
    ssh: {
      connected: true,
      hostname: 'smart-car',
      lastError: null,
      updatedAt: new Date().toISOString()
    },
    devices: {
      chassisSerial: true,
      chassisPath: '/dev/myserial',
      lidar: true,
      cameraDepth: true,
      cameraUvc: true,
      video0: true
    },
    ports: {
      control6000: true,
      video6500: true,
      rosbridge9090: true
    },
    services: {
      docker: true,
      container: 'old-container',
      chassis: true,
      lidar: true,
      camera: true,
      rosbridge: true,
      video: true
    }
  });

  const manager = new ServiceManager(
    {
      async run() {
        return {
          ok: false,
          code: 255,
          stdout: '',
          stderr: 'ssh: connect to host 192.168.137.169 port 22: No route to host',
          timedOut: false,
          durationMs: 12
        };
      }
    },
    {
      connect() {
        assert.fail('rosbridge should not reconnect when status refresh fails');
      }
    }
  );

  const status = await manager.refreshStatus();

  assert.equal(status.ssh.connected, false);
  assert.match(status.ssh.lastError, /No route to host/);
  assert.deepEqual(status.devices, {
    chassisSerial: false,
    chassisPath: null,
    lidar: false,
    cameraDepth: false,
    cameraUvc: false,
    video0: false
  });
  assert.deepEqual(status.ports, {
    control6000: false,
    video6500: false,
    rosbridge9090: false
  });
  assert.deepEqual(status.services, {
    docker: false,
    container: null,
    chassis: false,
    lidar: false,
    camera: false,
    rosbridge: false,
    video: false
  });
  assert.equal(runtime.status.canDrive, false);
});

test('rosbridge port alone does not unlock driving without a local websocket connection', () => {
  updateNavigation({ safetyState: 'READY' });
  updateRosbridge({
    connected: false,
    url: 'ws://192.168.43.137:9090',
    lastError: null
  });
  updateStatus({
    ssh: {
      connected: true,
      hostname: 'smart-car',
      lastError: null,
      updatedAt: new Date().toISOString()
    },
    devices: {
      chassisSerial: true,
      chassisPath: '/dev/myserial',
      lidar: true,
      cameraDepth: true,
      cameraUvc: true,
      video0: true
    },
    ports: {
      control6000: false,
      video6500: true,
      rosbridge9090: true
    },
    services: {
      docker: true,
      container: 'smartcar_icar_console',
      chassis: true,
      lidar: true,
      camera: true,
      rosbridge: true,
      video: true
    }
  });

  let current = snapshot().runtime.status;
  assert.equal(current.canDrive, false);
  assert.deepEqual(current.blockers, ['ROSBridge is not connected']);

  updateRosbridge({
    connected: true,
    url: 'ws://192.168.43.137:9090',
    lastError: null
  });
  current = snapshot().runtime.status;
  assert.equal(current.canDrive, true);
  assert.deepEqual(current.blockers, []);
});

test('service startup maps the discovered chassis device to /dev/myserial', () => {
  const script = buildRemoteStartScript();

  assert.match(script, /--device=\$chassis_device:\/dev\/myserial/);
  assert.match(script, /stat -Lc '%t:%T' "\$chassis_device"/);
  assert.match(script, /docker exec "\$cid" stat -Lc '%t:%T' \/dev\/myserial/);
});

test('safe-base startup uses the managed overlay and one navigation launch profile', () => {
  const script = buildRemoteStartScript({}, {
    enabled: true,
    mode: 'safe_base',
    overlaySetup: '/root/ros2_navigation_overlay/install/setup.bash'
  });

  assert.match(script, /navigation_setup='\/root\/ros2_navigation_overlay\/install\/setup\.bash'/);
  assert.match(script, /\. \$navigation_setup/);
  assert.match(script, /export ROS_LOCALHOST_ONLY=1/);
  assert.match(script, /FASTRTPS_DEFAULT_PROFILES_FILE=.*fastdds_localhost\.xml/);
  assert.match(script, /ros2 launch icar_navigation safe_base\.launch\.py/);
  assert.match(
    script,
    /\$ros_setup; \. \$navigation_setup; ros2 launch rosbridge_server rosbridge_websocket_launch\.xml/,
    'rosbridge must source the custom interface overlay before serving web service calls'
  );
  assert.match(script, /navigation_enabled=1/);
  assert.match(script, /\/home\/jetson\/ros2_navigation_overlay:\/root\/ros2_navigation_overlay/);
});

test('reused or replaced containers receive a zero-only stop before clean restart', () => {
  const script = buildRemoteStartScript({}, {
    enabled: true,
    mode: 'safe_base'
  });

  assert.match(script, /stop_container_safely\(\)/);
  assert.match(
    script,
    /ros2 topic pub --once \/cmd_vel_manual geometry_msgs\/msg\/Twist '\{linear: \{x: 0\.0, y: 0\.0, z: 0\.0\}, angular: \{x: 0\.0, y: 0\.0, z: 0\.0\}\}'/
  );
  assert.match(script, /pkill -TERM -f/);
  assert.match(script, /docker restart -t 2 "\$cid"/);
  assert.ok(
    script.indexOf('stop_container_safely "$cid"') <
      script.indexOf('docker rm -f "$cid"'),
    'container replacement must stop safely before forced removal'
  );
});

test('SSH emergency fallback prefers the arbiter and only falls back to a direct zero', async () => {
  let script = '';
  const manager = new ServiceManager(
    {
      async run(command) {
        script = command.script;
        return { ok: true, code: 0, stdout: '', stderr: '', timedOut: false, durationMs: 1 };
      }
    },
    {}
  );

  await manager.emergencyStopFallback('test');

  assert.match(script, /grep -Fxq \/cmd_vel_arbiter/);
  assert.match(script, /ros2 topic pub --once \/cmd_vel_manual geometry_msgs\/msg\/Twist/);
  assert.match(script, /ros2 topic pub --once \/cmd_vel geometry_msgs\/msg\/Twist/);
  assert.doesNotMatch(script, /linear: \{x: (?!0\.0)/);
  assert.doesNotMatch(script, /angular: \{x: 0\.0, y: 0\.0, z: (?!0\.0)/);
});

test('demo startup is fail-safe and never auto-starts patrol', () => {
  const script = buildRemoteStartScript({}, {
    enabled: true,
    mode: 'demo',
    map: '/root/maps/campus_map.yaml',
    routeFile: '/root/routes/patrol.yaml',
    autoStartPatrol: true
  });

  assert.match(script, /ros2 launch icar_navigation demo\.launch\.py/);
  assert.match(script, /map:='\/root\/maps\/campus_map\.yaml'/);
  assert.match(script, /route_file:='\/root\/routes\/patrol\.yaml'/);
  assert.match(script, /auto_start_patrol:=false/);
});

test('mapping startup requires both Cartographer processes to stay alive', () => {
  const script = buildRemoteStartScript({}, {
    enabled: true,
    mode: 'mapping'
  });

  assert.match(script, /navigation_mode='mapping'/);
  assert.match(script, /for required in cartographer_node occupancy_grid_node/);
  assert.match(script, /Required \$navigation_mode process is missing/);
  assert.match(
    script,
    /Traceback\|FATAL\|process has died\|Failed to bring up\|SubstitutionFailure/
  );
});
