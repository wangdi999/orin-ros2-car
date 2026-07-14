import { addLog, runtime, updateStatus } from './state.mjs';
import { bash, shellQuote } from './ssh.mjs';

export class ServiceManager {
  constructor(sshExecutor, rosbridge, getConfig = () => ({})) {
    this.ssh = sshExecutor;
    this.rosbridge = rosbridge;
    this.getConfig = getConfig;
  }

  async refreshStatus() {
    const result = await this.ssh.run(bash(remoteStatusScript()), { timeoutMs: 15000 });
    if (!result.ok) {
      const summary = summarizeFailure(result);
      updateStatus(remoteOfflineStatus(summary));
      addLog('warn', 'ssh', `Status check failed: ${summary}`);
      return runtime.status;
    }

    const fields = parseKeyValue(result.stdout);
    const nextStatus = {
      ssh: {
        connected: true,
        hostname: fields.HOSTNAME || null,
        lastError: null,
        updatedAt: new Date().toISOString()
      },
      devices: {
        chassisSerial: bool(fields.DEVICE_CHASSIS),
        chassisPath: fields.DEVICE_CHASSIS_PATH || null,
        lidar: bool(fields.DEVICE_RPLIDAR),
        cameraDepth: bool(fields.DEVICE_ASTRADEPTH),
        cameraUvc: bool(fields.DEVICE_ASTRAUVC),
        video0: bool(fields.DEVICE_VIDEO0)
      },
      ports: {
        control6000: bool(fields.PORT_6000),
        video6500: bool(fields.PORT_6500),
        rosbridge9090: bool(fields.PORT_9090)
      },
      services: {
        docker: bool(fields.DOCKER_RUNNING),
        container: fields.CONTAINER_ID || null,
        chassis: bool(fields.SERVICE_CHASSIS),
        lidar: bool(fields.SERVICE_LIDAR),
        camera: bool(fields.SERVICE_CAMERA),
        rosbridge: bool(fields.SERVICE_ROSBRIDGE) || bool(fields.PORT_9090),
        video: bool(fields.SERVICE_VIDEO) || bool(fields.PORT_6500)
      }
    };
    updateStatus(nextStatus);
    if (nextStatus.ports.rosbridge9090) this.rosbridge.connect();
    return runtime.status;
  }

  async startServices() {
    const config = this.getConfig();
    const mode = config.navigation?.enabled === false ? 'legacy' : config.navigation?.mode ?? 'safe_base';
    addLog('info', 'services', `Starting Jetson Docker, ${mode} ROS profile, rosbridge, and camera stream`);
    const result = await this.ssh.run(
      bash(buildRemoteStartScript(config.video, config.navigation)),
      { timeoutMs: 25000 }
    );
    if (!result.ok) {
      const summary = summarizeFailure(result);
      addLog('error', 'services', `Start failed: ${summary}`, {
        code: result.code,
        stderr: tail(result.stderr)
      });
      await this.refreshStatus();
      return { ok: false, error: summary, status: runtime.status };
    }
    runtime.startedByConsole = true;
    addLog('info', 'services', 'Start commands accepted on Jetson');
    await this.refreshStatus();
    this.rosbridge.connect();
    return { ok: true, stdout: tail(result.stdout), status: runtime.status };
  }

  async stopServices() {
    if (!runtime.startedByConsole) {
      addLog('warn', 'services', 'Stop skipped because this API session did not start the car-side services');
      return { ok: true, skipped: true, status: runtime.status };
    }
    addLog('info', 'services', 'Stopping services started by this console session');
    const result = await this.ssh.run(bash(remoteStopScript()), { timeoutMs: 12000 });
    runtime.startedByConsole = false;
    if (!result.ok) {
      const summary = summarizeFailure(result);
      addLog('error', 'services', `Stop failed: ${summary}`, {
        code: result.code,
        stderr: tail(result.stderr)
      });
      await this.refreshStatus();
      return { ok: false, error: summary, status: runtime.status };
    }
    await this.refreshStatus();
    return { ok: true, stdout: tail(result.stdout), status: runtime.status };
  }

  async emergencyStopFallback(reason) {
    addLog('warn', 'safety', `Using SSH fallback stop: ${reason}`);
    const result = await this.ssh.run(bash(remoteEmergencyStopScript()), { timeoutMs: 7000 });
    if (!result.ok) {
      addLog('error', 'safety', `SSH fallback stop failed: ${summarizeFailure(result)}`, {
        code: result.code,
        stderr: tail(result.stderr)
      });
      return false;
    }
    return true;
  }
}

function bool(value) {
  return String(value).trim() === '1' || String(value).trim().toLowerCase() === 'true';
}

function parseKeyValue(text) {
  const fields = {};
  for (const line of text.split(/\r?\n/)) {
    const index = line.indexOf('=');
    if (index <= 0) continue;
    fields[line.slice(0, index).trim()] = line.slice(index + 1).trim();
  }
  return fields;
}

function tail(text, max = 700) {
  const cleaned = String(text ?? '').trim();
  if (cleaned.length <= max) return cleaned;
  return cleaned.slice(-max);
}

function summarizeFailure(result) {
  if (result.timedOut) return `timeout after ${result.durationMs} ms`;
  return tail(result.stderr || result.stdout || `exit code ${result.code}`) || 'unknown error';
}

function remoteOfflineStatus(lastError) {
  return {
    ssh: {
      connected: false,
      hostname: null,
      lastError,
      updatedAt: new Date().toISOString()
    },
    devices: {
      chassisSerial: false,
      chassisPath: null,
      lidar: false,
      cameraDepth: false,
      cameraUvc: false,
      video0: false
    },
    ports: {
      control6000: false,
      video6500: false,
      rosbridge9090: false
    },
    services: {
      docker: false,
      container: null,
      chassis: false,
      lidar: false,
        camera: false,
      rosbridge: false,
      video: false
    }
  };
}

function commonContainerLookup() {
  return `
find_container() {
  local cid
  cid="$(docker ps -q --filter name=smartcar_icar_console | head -n 1)"
  if [ -z "$cid" ]; then
    cid="$(docker ps -q --filter ancestor=icar/ros-foxy:1.0.2 | head -n 1)"
  fi
  printf '%s' "$cid"
}
find_named_container() {
  docker ps -aq --filter name=smartcar_icar_console | head -n 1
}
`;
}

function remoteStatusScript() {
return `
set +e
${commonContainerLookup()}
exists() { [ -e "$1" ] && printf '1' || printf '0'; }
port_open() { ss -ltn 2>/dev/null | grep -Eq "[:.]$1[[:space:]]"; }
proc_host() { pgrep -af "$1" >/dev/null 2>&1; }
find_chassis_device() {
  local rplidar_real dev dev_real
  rplidar_real="$(readlink -f /dev/rplidar 2>/dev/null || true)"
  if [ -e /dev/myserial ]; then
    printf '/dev/myserial'
    return
  fi
  for dev in /dev/ttyUSB* /dev/ttyACM*; do
    [ -e "$dev" ] || continue
    dev_real="$(readlink -f "$dev" 2>/dev/null || true)"
    if [ -n "$rplidar_real" ] && [ "$dev_real" = "$rplidar_real" ]; then
      continue
    fi
    printf '%s' "$dev"
    return
  done
}
printf 'HOSTNAME=%s\\n' "$(hostname 2>/dev/null)"
printf 'DEVICE_ASTRADEPTH=%s\\n' "$(exists /dev/astradepth)"
printf 'DEVICE_ASTRAUVC=%s\\n' "$(exists /dev/astrauvc)"
printf 'DEVICE_RPLIDAR=%s\\n' "$(exists /dev/rplidar)"
printf 'DEVICE_VIDEO0=%s\\n' "$(exists /dev/video0)"
chassis_device="$(find_chassis_device)"
if [ -n "$chassis_device" ]; then
  printf 'DEVICE_CHASSIS=1\\nDEVICE_CHASSIS_PATH=%s\\n' "$chassis_device"
else
  printf 'DEVICE_CHASSIS=0\\nDEVICE_CHASSIS_PATH=\\n'
fi
port_open 6000 && printf 'PORT_6000=1\\n' || printf 'PORT_6000=0\\n'
port_open 6500 && printf 'PORT_6500=1\\n' || printf 'PORT_6500=0\\n'
port_open 9090 && printf 'PORT_9090=1\\n' || printf 'PORT_9090=0\\n'
cid="$(find_container)"
printf 'CONTAINER_ID=%s\\n' "$cid"
if [ -n "$cid" ]; then
  printf 'DOCKER_RUNNING=1\\n'
  proc_table="$(docker exec "$cid" ps -ef 2>/dev/null || true)"
  case "$proc_table" in *Mcnamu_driver_X3*) printf 'SERVICE_CHASSIS=1\\n' ;; *) printf 'SERVICE_CHASSIS=0\\n' ;; esac
  case "$proc_table" in *sllidar_launch.py*|*sllidar_node*) printf 'SERVICE_LIDAR=1\\n' ;; *) printf 'SERVICE_LIDAR=0\\n' ;; esac
  case "$proc_table" in *astra.launch.xml*|*astra_camera*) printf 'SERVICE_CAMERA=1\\n' ;; *) printf 'SERVICE_CAMERA=0\\n' ;; esac
  case "$proc_table" in *rosbridge_websocket_launch.xml*|*rosbridge_websocket*) printf 'SERVICE_ROSBRIDGE=1\\n' ;; *) printf 'SERVICE_ROSBRIDGE=0\\n' ;; esac
else
  printf 'DOCKER_RUNNING=0\\nSERVICE_CHASSIS=0\\nSERVICE_LIDAR=0\\nSERVICE_CAMERA=0\\nSERVICE_ROSBRIDGE=0\\n'
fi
proc_host '[s]martcar_mjpeg_video0.py|[R]osmaster-App/rosmaster/app.py|[p]ython3 app.py' && printf 'SERVICE_VIDEO=1\\n' || printf 'SERVICE_VIDEO=0\\n'
`;
}

export function buildRemoteStartScript(videoConfig = {}, navigationConfig = {}) {
  const video = normalizeVideoConfig(videoConfig);
  const navigation = normalizeNavigationConfig(navigationConfig);
  const navigationLaunch = navigationLaunchCommand(navigation);
  const zeroTwist = shellQuote(
    '{linear: {x: 0.0, y: 0.0, z: 0.0}, angular: {x: 0.0, y: 0.0, z: 0.0}}'
  );
  return `
set +e
navigation_enabled=${navigation.enabled ? '1' : '0'}
navigation_mode=${shellQuote(navigation.mode)}
navigation_setup=${shellQuote(navigation.overlaySetup)}
navigation_launch=${shellQuote(navigation.launchFile)}
${commonContainerLookup()}
port_open() { ss -ltn 2>/dev/null | grep -Eq "[:.]$1[[:space:]]"; }
find_chassis_device() {
  local rplidar_real dev dev_real
  rplidar_real="$(readlink -f /dev/rplidar 2>/dev/null || true)"
  if [ -e /dev/myserial ]; then
    printf '/dev/myserial'
    return
  fi
  for dev in /dev/ttyUSB* /dev/ttyACM*; do
    [ -e "$dev" ] || continue
    dev_real="$(readlink -f "$dev" 2>/dev/null || true)"
    if [ -n "$rplidar_real" ] && [ "$dev_real" = "$rplidar_real" ]; then
      continue
    fi
    printf '%s' "$dev"
    return
  done
}
container_needs_recreate() {
  local cid="$1" chassis_device host_device container_device
  [ -n "$cid" ] || return 1
  if [ "$navigation_enabled" = '1' ] \
      && [ -f /home/jetson/ros2_navigation_overlay/.ready ] \
      && ! docker inspect "$cid" --format '{{range .Mounts}}{{println .Destination}}{{end}}' 2>/dev/null \
          | grep -Fxq '/root/ros2_navigation_overlay'; then
    return 0
  fi
  if ! docker inspect "$cid" --format '{{range .Mounts}}{{println .Destination}}{{end}}' 2>/dev/null \
      | grep -Fxq '/root/routes'; then
    return 0
  fi
  for dev in /dev/astradepth /dev/astrauvc /dev/video0 /dev/rplidar; do
    if [ -e "$dev" ] && ! docker exec "$cid" test -e "$dev" >/dev/null 2>&1; then
      return 0
    fi
  done
  chassis_device="$(find_chassis_device)"
  if [ -n "$chassis_device" ]; then
    if ! docker exec "$cid" test -e /dev/myserial >/dev/null 2>&1; then
      return 0
    fi
    host_device="$(stat -Lc '%t:%T' "$chassis_device" 2>/dev/null || true)"
    container_device="$(docker exec "$cid" stat -Lc '%t:%T' /dev/myserial 2>/dev/null || true)"
    if [ -z "$host_device" ] || [ "$host_device" != "$container_device" ]; then
      return 0
    fi
  fi
  return 1
}
stop_container_safely() {
  local target_cid="$1"
  docker exec "$target_cid" /bin/bash -c "
    if [ \"$navigation_enabled\" = '1' ] \\
        && [ -f /root/ros2_navigation_overlay/install/share/icar_navigation/config/fastdds_localhost.xml ]; then
      export ROS_LOCALHOST_ONLY=1
      export FASTRTPS_DEFAULT_PROFILES_FILE=/root/ros2_navigation_overlay/install/share/icar_navigation/config/fastdds_localhost.xml
    fi
    for setup in /opt/ros/foxy/setup.bash /root/icar_ros2_ws/icar_ws/install/setup.bash /root/icar_ros2_ws/software/library_ws/install/setup.bash /root/ros2_navigation_overlay/install/setup.bash; do
      [ -f \"\$setup\" ] && source \"\$setup\"
    done
    timeout 3 ros2 topic pub --once /cmd_vel geometry_msgs/msg/Twist ${zeroTwist}
  " >/tmp/smartcar_pre_restart_zero.log 2>&1 || true
  sleep 1
  docker exec "$target_cid" /bin/bash -c "pkill -TERM -f '[M]cnamu_driver_X3|[s]llidar_launch.py|[s]llidar_node|[c]md_vel_arbiter|[s]afety_manager|[p]atrol_manager|[c]artographer_node|[o]ccupancy_grid_node|[a]mcl|[c]ontroller_server|[p]lanner_server|[r]ecoveries_server|[b]t_navigator|[l]ifecycle_manager|[a]stra.launch.xml|[a]stra_camera|[r]osbridge_websocket_launch.xml|[r]osbridge_websocket|[r]osapi_node|[r]os2 launch icar_navigation' || true" || true
  sleep 1
}
start_video_stream() {
  pkill -f '[R]osmaster-App/rosmaster/app.py' 2>/dev/null || true
  pkill -f '[a]pp_sim_run.py' 2>/dev/null || true
  pkill -f '[p]ython3 app.py' 2>/dev/null || true
  pkill -f '[p]ython3 .*/app.py' 2>/dev/null || true
  pkill -f '[s]martcar_video_wrapper.py' 2>/dev/null || true
  pkill -f '[s]martcar_mjpeg_video0.py' 2>/dev/null || true
  cat >/tmp/smartcar_mjpeg_video0.py <<'PY'
import cv2 as cv
import glob
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

WIDTH = ${video.width}
HEIGHT = ${video.height}
FPS = ${video.fps}
JPEG_QUALITY = ${video.jpegQuality}
FRAME_DELAY = 1.0 / max(FPS, 1)
VIDEO_SOURCES = sorted(glob.glob('/dev/video*')) + [0]
latest_jpeg = None
latest_source = None
latest_error = 'camera capture is starting'
frame_lock = threading.Lock()

def open_camera():
    for source in VIDEO_SOURCES:
        cap = cv.VideoCapture(source, cv.CAP_V4L2)
        cap.set(cv.CAP_PROP_FRAME_WIDTH, WIDTH)
        cap.set(cv.CAP_PROP_FRAME_HEIGHT, HEIGHT)
        cap.set(cv.CAP_PROP_FPS, FPS)
        cap.set(cv.CAP_PROP_BUFFERSIZE, 1)
        if not cap.isOpened():
            cap.release()
            continue

        deadline = time.time() + 2.0
        while time.time() < deadline:
            ok, frame = cap.read()
            if ok:
                return source, cap, frame
            time.sleep(0.05)
        cap.release()
    return None, None, None

def capture_loop():
    global latest_jpeg, latest_source, latest_error
    while True:
        source, cap, frame = open_camera()
        if cap is None:
            with frame_lock:
                latest_jpeg = None
                latest_source = None
                latest_error = 'no usable /dev/video* camera'
            time.sleep(1.0)
            continue

        with frame_lock:
            latest_source = source
            latest_error = None

        try:
            while True:
                ok, jpeg = cv.imencode('.jpg', frame, [int(cv.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])
                if ok:
                    with frame_lock:
                        latest_jpeg = jpeg.tobytes()
                        latest_source = source
                        latest_error = None
                ok, frame = cap.read()
                if not ok:
                    with frame_lock:
                        latest_error = f'{source} stopped producing frames'
                    break
                time.sleep(FRAME_DELAY)
        finally:
            cap.release()
            time.sleep(0.25)

class MjpegHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def do_GET(self):
        if self.path not in ('/', '/video_feed'):
            self.send_error(404)
            return
        if self.path == '/':
            body = b'<html><body><img src="/video_feed"></body></html>'
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        deadline = time.time() + 3.0
        while time.time() < deadline:
            with frame_lock:
                data = latest_jpeg
                source = latest_source
                error = latest_error
            if data is not None:
                break
            time.sleep(0.05)

        if data is None:
            self.send_error(503, error or 'video frame is not ready')
            return

        self.send_response(200)
        self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=frame')
        self.send_header('X-Smartcar-Video-Source', str(source))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()

        try:
            while True:
                with frame_lock:
                    data = latest_jpeg
                if data is None:
                    time.sleep(0.05)
                    continue
                self.wfile.write(b'--frame\\r\\n')
                self.wfile.write(b'Content-Type: image/jpeg\\r\\n')
                self.wfile.write(f'Content-Length: {len(data)}\\r\\n\\r\\n'.encode('ascii'))
                self.wfile.write(data)
                self.wfile.write(b'\\r\\n')
                self.wfile.flush()
                time.sleep(FRAME_DELAY)
        except (BrokenPipeError, ConnectionResetError):
            pass

threading.Thread(target=capture_loop, daemon=True).start()
server = ThreadingHTTPServer(('0.0.0.0', 6500), MjpegHandler)
server.serve_forever()
PY
  setsid -f bash -lc 'exec python3 /tmp/smartcar_mjpeg_video0.py >/tmp/smartcar_video_6500.log 2>&1'
}
enable_chassis_auto_report() {
  docker exec "$cid" /bin/bash -c "timeout 3 python3 - <<'PY'
from Rosmaster_Lib import Rosmaster
import time

car = Rosmaster(com='/dev/myserial')
car.set_auto_report_state(True)
time.sleep(0.05)
try:
    car.ser.close()
except Exception:
    pass
PY" >/tmp/smartcar_chassis_autoreport.log 2>&1 || true
}
cid="$(find_container)"
if [ -n "$cid" ]; then
  :
else
  cid="$(find_named_container)"
  if [ -n "$cid" ]; then
    docker start "$cid" >/dev/null || cid=""
    sleep 1
    cid="$(find_container)"
  fi
fi
if [ -n "$cid" ] && container_needs_recreate "$cid"; then
  stop_container_safely "$cid"
  docker rm -f "$cid" >/dev/null 2>&1 || true
  cid=""
fi
container_created=0
if [ -z "$cid" ]; then
  mkdir -p /home/jetson/ros2_navigation_overlay /home/jetson/maps /home/jetson/routes
  device_args=""
  for dev in /dev/astradepth /dev/astrauvc /dev/video0 /dev/rplidar /dev/input; do
    if [ -e "$dev" ]; then
      device_args="$device_args --device=$dev"
    fi
  done
  chassis_device="$(find_chassis_device)"
  if [ -n "$chassis_device" ]; then
    device_args="$device_args --device=$chassis_device:/dev/myserial"
  fi
  cid="$(docker run -d --name smartcar_icar_console --net=host \
    --env DISPLAY --env QT_X11_NO_MITSHM=1 \
    -v /tmp/.X11-unix:/tmp/.X11-unix \
    -v /home/jetson/temp:/root/icar_ros2_ws/temp \
    -v /home/jetson/rosboard:/root/rosboard \
    -v /home/jetson/maps:/root/maps \
    -v /home/jetson/routes:/root/routes \
    -v /home/jetson/ros2_navigation_overlay:/root/ros2_navigation_overlay \
    $device_args \
    icar/ros-foxy:1.0.2 tail -f /dev/null)"
  container_created=1
fi
if [ -z "$cid" ]; then
  echo 'No icar/ros-foxy:1.0.2 container available' >&2
  exit 30
fi
if [ "$navigation_enabled" = '1' ] \
    && ! docker exec "$cid" test -f "$navigation_setup"; then
  echo "Navigation overlay is not ready: $navigation_setup" >&2
  exit 41
fi
if [ "$container_created" = '0' ]; then
  stop_container_safely "$cid"
  docker restart -t 2 "$cid" >/dev/null || exit 31
  sleep 1
  cid="$(find_container)"
  if [ -z "$cid" ]; then
    echo 'ROS container did not recover after restart' >&2
    exit 32
  fi
fi
ros_setup='export ROS_LOCALHOST_ONLY=1; export FASTRTPS_DEFAULT_PROFILES_FILE=/root/ros2_navigation_overlay/install/share/icar_navigation/config/fastdds_localhost.xml; . /opt/ros/foxy/setup.bash; . /root/icar_ros2_ws/icar_ws/install/setup.bash; . /root/icar_ros2_ws/software/library_ws/install/setup.bash'
chassis_device="$(find_chassis_device)"
if [ -n "$chassis_device" ]; then
  enable_chassis_auto_report
fi
if [ "$navigation_enabled" = '1' ]; then
  docker exec -d "$cid" /bin/bash -c "$ros_setup; . $navigation_setup; ${navigationLaunch} >/tmp/smartcar_navigation.log 2>&1"
else
  if [ -n "$chassis_device" ]; then
    docker exec -d "$cid" /bin/bash -c "$ros_setup; ros2 run icar_bringup Mcnamu_driver_X3 >/tmp/smartcar_chassis.log 2>&1"
  else
    echo 'Skipping chassis driver: /dev/myserial or a non-lidar serial device was not found' >&2
  fi
  docker exec -d "$cid" /bin/bash -c "$ros_setup; ros2 launch sllidar_ros2 sllidar_launch.py >/tmp/smartcar_lidar.log 2>&1"
fi
docker exec -d "$cid" /bin/bash -c "$ros_setup; ros2 launch rosbridge_server rosbridge_websocket_launch.xml >/tmp/smartcar_rosbridge.log 2>&1"
start_video_stream
sleep 5
if [ "$navigation_enabled" = '1' ]; then
  process_table="$(docker exec "$cid" ps -ef 2>/dev/null || true)"
  launch_health_ok=1
  require_process() {
    case "$process_table" in
      *"$1"*) return 0 ;;
      *) echo "Required $navigation_mode process is missing: $1" >&2; return 1 ;;
    esac
  }
  require_process "ros2 launch icar_navigation $navigation_launch" || launch_health_ok=0
  for required in Mcnamu_driver_X3 sllidar_node ekf_node cmd_vel_arbiter safety_manager; do
    require_process "$required" || launch_health_ok=0
  done
  case "$navigation_mode" in
    mapping)
      for required in cartographer_node occupancy_grid_node; do
        require_process "$required" || launch_health_ok=0
      done
      ;;
    navigation|demo)
      for required in amcl map_server controller_server planner_server bt_navigator patrol_manager; do
        require_process "$required" || launch_health_ok=0
      done
      ;;
  esac
  if docker exec "$cid" grep -Eq \
      'Traceback|FATAL|process has died|Failed to bring up|SubstitutionFailure' \
      /tmp/smartcar_navigation.log 2>/dev/null; then
    echo "Navigation launch log contains a fatal startup marker" >&2
    launch_health_ok=0
  fi
  if [ "$launch_health_ok" -ne 1 ]; then
    docker exec "$cid" tail -n 120 /tmp/smartcar_navigation.log >&2 || true
    exit 42
  fi
fi
echo "CID=$cid"
`;
}

function normalizeVideoConfig(config = {}) {
  return {
    width: clampInteger(config.width, 160, 1920, 640),
    height: clampInteger(config.height, 120, 1080, 480),
    fps: clampInteger(config.fps, 1, 60, 20),
    jpegQuality: clampInteger(config.jpegQuality, 20, 95, 70)
  };
}

function normalizeNavigationConfig(config = {}) {
  const mode = ['safe_base', 'mapping', 'navigation', 'demo'].includes(config.mode)
    ? config.mode
    : 'safe_base';
  const launchFiles = {
    safe_base: 'safe_base.launch.py',
    mapping: 'mapping.launch.py',
    navigation: 'navigation.launch.py',
    demo: 'demo.launch.py'
  };
  return {
    enabled: config.enabled !== false,
    mode,
    launchFile: launchFiles[mode],
    overlaySetup: safePosixPath(
      config.overlaySetup,
      '/root/ros2_navigation_overlay/install/setup.bash'
    ),
    map: safePosixPath(
      config.map,
      '/root/ros2_navigation_overlay/install/share/icar_navigation/maps/campus_map.yaml'
    ),
    routeFile: safePosixPath(
      config.routeFile,
      '/root/ros2_navigation_overlay/install/share/icar_navigation/config/patrol_route.yaml'
    ),
    maxLinearMps: clampNumber(config.maxLinearMps, 0.05, 0.1, 0.05),
    maxAngularRps: clampNumber(config.maxAngularRps, 0.2, 0.4, 0.2)
  };
}

function navigationLaunchCommand(config) {
  const args = [
    'ros2 launch icar_navigation',
    config.launchFile,
    `max_linear:=${shellQuote(String(config.maxLinearMps))}`,
    `max_angular:=${shellQuote(String(config.maxAngularRps))}`
  ];
  if (config.mode === 'navigation' || config.mode === 'demo') {
    args.push(`map:=${shellQuote(config.map)}`);
    args.push(`route_file:=${shellQuote(config.routeFile)}`);
  }
  if (config.mode === 'demo') {
    args.push('auto_start_patrol:=false');
  }
  return args.join(' ');
}

function safePosixPath(value, fallback) {
  const path = String(value ?? '').trim();
  return /^\/[A-Za-z0-9._/-]+$/.test(path) ? path : fallback;
}

function clampNumber(value, min, max, fallback) {
  const number = Number(value);
  if (!Number.isFinite(number)) return fallback;
  return Math.min(max, Math.max(min, number));
}

function clampInteger(value, min, max, fallback) {
  const number = Number(value);
  if (!Number.isFinite(number)) return fallback;
  return Math.min(max, Math.max(min, Math.round(number)));
}

function remoteStopScript() {
  return `
set +e
${commonContainerLookup()}
cid="$(find_container)"
if [ -n "$cid" ]; then
  docker exec "$cid" bash -lc "pkill -f '[M]cnamu_driver_X3|[s]llidar_launch.py|[s]llidar_node|[c]md_vel_arbiter|[s]afety_manager|[p]atrol_manager|[c]artographer_node|[o]ccupancy_grid_node|[a]mcl|[c]ontroller_server|[p]lanner_server|[r]ecoveries_server|[b]t_navigator|[l]ifecycle_manager|[a]stra.launch.xml|[a]stra_camera|[r]osbridge_websocket_launch.xml|[r]osbridge_websocket|[r]os2 launch icar_navigation' || true"
fi
pkill -f 'Rosmaster-App/rosmaster/app.py' || true
pkill -f 'python3 app.py' || true
pkill -f 'python3 .*/app.py' || true
echo 'stop-issued'
`;
}

function remoteEmergencyStopScript() {
  const twist = shellQuote('{linear: {x: 0.0, y: 0.0, z: 0.0}, angular: {x: 0.0, y: 0.0, z: 0.0}}');
  return `
set +e
${commonContainerLookup()}
cid="$(find_container)"
if [ -z "$cid" ]; then
  echo 'No running icar container for fallback /cmd_vel publish' >&2
  exit 20
fi
docker exec "$cid" bash -lc "for setup in /opt/ros/foxy/setup.bash /root/icar_ros2_ws/icar_ws/install/setup.bash /root/icar_ros2_ws/software/library_ws/install/setup.bash /root/ros2_ws/install/setup.bash; do [ -f \\"\\$setup\\" ] && source \\"\\$setup\\"; done; timeout 3 ros2 topic pub --once /cmd_vel geometry_msgs/msg/Twist ${twist}"
`;
}
