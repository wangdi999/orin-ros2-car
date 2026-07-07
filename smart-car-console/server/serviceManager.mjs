import { ZERO_TWIST } from './control.mjs';
import { addLog, runtime, updateStatus } from './state.mjs';
import { bash } from './ssh.mjs';

export class ServiceManager {
  constructor(sshExecutor, rosbridge) {
    this.ssh = sshExecutor;
    this.rosbridge = rosbridge;
  }

  async refreshStatus() {
    const result = await this.ssh.run(bash(remoteStatusScript()), { timeoutMs: 15000 });
    if (!result.ok) {
      updateStatus({
        ssh: {
          connected: false,
          hostname: null,
          lastError: summarizeFailure(result),
          updatedAt: new Date().toISOString()
        },
        ports: {
          control6000: false,
          video6500: false,
          rosbridge9090: false
        },
        services: {
          ...runtime.status.services,
          rosbridge: false,
          video: false
        }
      });
      addLog('warn', 'ssh', `Status check failed: ${summarizeFailure(result)}`);
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
    addLog('info', 'services', 'Starting Jetson Docker, ROS nodes, rosbridge, and camera stream');
    const result = await this.ssh.run(bash(remoteStartScript()), { timeoutMs: 20000 });
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

function remoteStartScript() {
  return `
set +e
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
  local cid="$1"
  [ -n "$cid" ] || return 1
  for dev in /dev/astradepth /dev/astrauvc /dev/video0 /dev/rplidar; do
    if [ -e "$dev" ] && ! docker exec "$cid" test -e "$dev" >/dev/null 2>&1; then
      return 0
    fi
  done
  if [ -n "$(find_chassis_device)" ] && ! docker exec "$cid" test -e /dev/myserial >/dev/null 2>&1; then
    return 0
  fi
  return 1
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
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

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

        cap = cv.VideoCapture(0)
        cap.set(cv.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv.CAP_PROP_FRAME_HEIGHT, 480)
        if not cap.isOpened():
            self.send_error(503, 'video0 is not available')
            return

        self.send_response(200)
        self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=frame')
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()

        try:
            while True:
                ok, frame = cap.read()
                if not ok:
                    time.sleep(0.1)
                    continue
                ok, jpeg = cv.imencode('.jpg', frame, [int(cv.IMWRITE_JPEG_QUALITY), 70])
                if not ok:
                    continue
                data = jpeg.tobytes()
                self.wfile.write(b'--frame\\r\\n')
                self.wfile.write(b'Content-Type: image/jpeg\\r\\n')
                self.wfile.write(f'Content-Length: {len(data)}\\r\\n\\r\\n'.encode('ascii'))
                self.wfile.write(data)
                self.wfile.write(b'\\r\\n')
                self.wfile.flush()
                time.sleep(0.05)
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            cap.release()

server = ThreadingHTTPServer(('0.0.0.0', 6500), MjpegHandler)
server.serve_forever()
PY
  setsid -f bash -lc 'exec python3 /tmp/smartcar_mjpeg_video0.py >/tmp/smartcar_video_6500.log 2>&1'
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
  docker rm -f "$cid" >/dev/null 2>&1 || true
  cid=""
fi
if [ -z "$cid" ]; then
  device_args=""
  for dev in /dev/astradepth /dev/astrauvc /dev/video0 /dev/myserial /dev/rplidar /dev/input; do
    if [ -e "$dev" ]; then
      device_args="$device_args --device=$dev"
    fi
  done
  cid="$(docker run -d --name smartcar_icar_console --net=host \
    --env DISPLAY --env QT_X11_NO_MITSHM=1 \
    -v /tmp/.X11-unix:/tmp/.X11-unix \
    -v /home/jetson/temp:/root/icar_ros2_ws/temp \
    -v /home/jetson/rosboard:/root/rosboard \
    -v /home/jetson/maps:/root/maps \
    $device_args \
    icar/ros-foxy:1.0.2 tail -f /dev/null)"
fi
if [ -z "$cid" ]; then
  echo 'No icar/ros-foxy:1.0.2 container available' >&2
  exit 30
fi
ros_setup='. /opt/ros/foxy/setup.bash; . /root/icar_ros2_ws/icar_ws/install/setup.bash; . /root/icar_ros2_ws/software/library_ws/install/setup.bash'
chassis_device="$(find_chassis_device)"
docker exec "$cid" /bin/bash -c "pkill -f 'Mcnamu_driver_X3|sllidar_launch.py|sllidar_node|rosbridge_websocket_launch.xml|rosbridge_websocket|rosapi_node' || true"
sleep 1
if [ -n "$chassis_device" ]; then
  docker exec -d "$cid" /bin/bash -c "$ros_setup; ros2 run icar_bringup Mcnamu_driver_X3 >/tmp/smartcar_chassis.log 2>&1"
else
  echo 'Skipping chassis driver: /dev/myserial or a non-lidar serial device was not found' >&2
fi
docker exec -d "$cid" /bin/bash -c "$ros_setup; ros2 launch sllidar_ros2 sllidar_launch.py >/tmp/smartcar_lidar.log 2>&1"
docker exec -d "$cid" /bin/bash -c "$ros_setup; ros2 launch rosbridge_server rosbridge_websocket_launch.xml >/tmp/smartcar_rosbridge.log 2>&1"
start_video_stream
sleep 3
echo "CID=$cid"
`;
}

function remoteStopScript() {
  return `
set +e
${commonContainerLookup()}
cid="$(find_container)"
if [ -n "$cid" ]; then
  docker exec "$cid" bash -lc "pkill -f 'Mcnamu_driver_X3|sllidar_launch.py|sllidar_node|astra.launch.xml|astra_camera|rosbridge_websocket_launch.xml|rosbridge_websocket' || true"
fi
pkill -f 'Rosmaster-App/rosmaster/app.py' || true
pkill -f 'python3 app.py' || true
pkill -f 'python3 .*/app.py' || true
echo 'stop-issued'
`;
}

function remoteEmergencyStopScript() {
  const twist = JSON.stringify(ZERO_TWIST).replaceAll('"', '\\"');
  return `
set +e
${commonContainerLookup()}
cid="$(find_container)"
if [ -z "$cid" ]; then
  echo 'No running icar container for fallback /cmd_vel publish' >&2
  exit 20
fi
docker exec "$cid" bash -lc "for setup in /opt/ros/foxy/setup.bash /root/icar_ros2_ws/icar_ws/install/setup.bash /root/icar_ros2_ws/software/library_ws/install/setup.bash /root/ros2_ws/install/setup.bash; do [ -f \\"\\$setup\\" ] && source \\"\\$setup\\"; done; timeout 3 ros2 topic pub --once /cmd_vel geometry_msgs/msg/Twist \\"${twist}\\""
`;
}
