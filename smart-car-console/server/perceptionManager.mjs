import { bash } from './ssh.mjs';
import { discoverPerceptionTopics, parseTopicListTypes } from './topicDiscovery.mjs';
import { addLog, runtime, updatePerception } from './state.mjs';

export class PerceptionManager {
  constructor(sshExecutor, rosbridge, getConfig) {
    this.ssh = sshExecutor;
    this.rosbridge = rosbridge;
    this.getConfig = getConfig;
  }

  async refreshStatus() {
    const config = this.getConfig();
    if (!config.car.sshPassword) {
      const message = 'SSH password is not saved; perception discovery is waiting for car credentials.';
      updatePerception({ lastError: message });
      this.rosbridge.setPerceptionSubscriptions(runtime.perception.topicDiscovery.matches);
      return runtime.perception;
    }

    const result = await this.ssh.run(bash(remotePerceptionStatusScript()), { timeoutMs: 15000 });
    if (!result.ok) {
      const error = summarizeFailure(result);
      updatePerception({ lastError: error });
      addLog('warn', 'perception', `Perception status failed: ${error}`);
      this.rosbridge.setPerceptionSubscriptions(runtime.perception.topicDiscovery.matches);
      return runtime.perception;
    }

    const sections = parseSections(result.stdout);
    const fields = parseKeyValue(sections.STATUS ?? '');
    const topics = parseTopicListTypes(sections.TOPICS ?? '');
    const topicDiscovery = discoverPerceptionTopics(topics, runtime.perception.topicDiscovery);
    updatePerception({
      services: {
        astraCamera: bool(fields.SERVICE_ASTRA_CAMERA),
        colorHsv: bool(fields.SERVICE_COLOR_HSV),
        colorTracker: bool(fields.SERVICE_COLOR_TRACKER)
      },
      topicDiscovery,
      lastError: null
    });
    this.rosbridge.setPerceptionSubscriptions(topicDiscovery.matches);
    return runtime.perception;
  }

  async startPerception() {
    addLog('info', 'perception', 'Starting Astra camera and safe tracking preview services');
    const result = await this.ssh.run(bash(remoteStartPerceptionScript()), { timeoutMs: 20000 });
    if (!result.ok) {
      const error = summarizeFailure(result);
      updatePerception({ lastError: error });
      addLog('error', 'perception', `Start failed: ${error}`);
      await this.refreshStatus();
      return { ok: false, error, perception: runtime.perception };
    }
    addLog('info', 'perception', 'Perception start commands accepted on Jetson');
    await this.refreshStatus();
    return { ok: true, stdout: tail(result.stdout), perception: runtime.perception };
  }

  async stopPerception() {
    addLog('info', 'perception', 'Stopping Astra and tracking preview services');
    const result = await this.ssh.run(bash(remoteStopPerceptionScript()), { timeoutMs: 12000 });
    if (!result.ok) {
      const error = summarizeFailure(result);
      updatePerception({ lastError: error });
      addLog('error', 'perception', `Stop failed: ${error}`);
      await this.refreshStatus();
      return { ok: false, error, perception: runtime.perception };
    }
    await this.refreshStatus();
    return { ok: true, stdout: tail(result.stdout), perception: runtime.perception };
  }
}

function parseSections(text) {
  const sections = {};
  let current = null;
  for (const line of String(text ?? '').split(/\r?\n/)) {
    const match = line.match(/^@@([A-Z_]+)@@$/);
    if (match) {
      current = match[1];
      sections[current] = '';
      continue;
    }
    if (current) sections[current] += `${line}\n`;
  }
  return sections;
}

function parseKeyValue(text) {
  const fields = {};
  for (const line of String(text ?? '').split(/\r?\n/)) {
    const index = line.indexOf('=');
    if (index <= 0) continue;
    fields[line.slice(0, index).trim()] = line.slice(index + 1).trim();
  }
  return fields;
}

function bool(value) {
  return String(value).trim() === '1' || String(value).trim().toLowerCase() === 'true';
}

function summarizeFailure(result) {
  if (result.timedOut) return `timeout after ${result.durationMs} ms`;
  return tail(result.stderr || result.stdout || `exit code ${result.code}`) || 'unknown error';
}

function tail(text, max = 900) {
  const cleaned = String(text ?? '').trim();
  if (cleaned.length <= max) return cleaned;
  return cleaned.slice(-max);
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
`;
}

function rosSetup() {
  return `. /opt/ros/foxy/setup.bash; for setup in /root/icar_ros2_ws/icar_ws/install/setup.bash /root/icar_ros2_ws/software/library_ws/install/setup.bash /root/ros2_ws/install/setup.bash; do [ -f "$setup" ] && . "$setup"; done`;
}

export function remotePerceptionStatusScript() {
  return `
set +e
${commonContainerLookup()}
cid="$(find_container)"
printf '@@STATUS@@\\n'
if [ -z "$cid" ]; then
  printf 'SERVICE_ASTRA_CAMERA=0\\nSERVICE_COLOR_HSV=0\\nSERVICE_COLOR_TRACKER=0\\n'
  printf '@@TOPICS@@\\n'
  exit 0
fi
proc_table="$(docker exec "$cid" ps -ef 2>/dev/null || true)"
case "$proc_table" in *astra.launch.xml*|*astra_camera*) printf 'SERVICE_ASTRA_CAMERA=1\\n' ;; *) printf 'SERVICE_ASTRA_CAMERA=0\\n' ;; esac
case "$proc_table" in *colorHSV*) printf 'SERVICE_COLOR_HSV=1\\n' ;; *) printf 'SERVICE_COLOR_HSV=0\\n' ;; esac
case "$proc_table" in *colorTracker*) printf 'SERVICE_COLOR_TRACKER=1\\n' ;; *) printf 'SERVICE_COLOR_TRACKER=0\\n' ;; esac
printf '@@TOPICS@@\\n'
docker exec "$cid" bash -lc '${rosSetup()}; timeout 5 ros2 topic list --no-daemon -t' 2>/dev/null || true
`;
}

function remoteStartPerceptionScript() {
  return `
set +e
${commonContainerLookup()}
cid="$(find_container)"
if [ -z "$cid" ]; then
  echo 'No running icar container for perception services' >&2
  exit 20
fi
ros_setup='${rosSetup()}'
docker exec "$cid" bash -lc "pkill -f 'astra.launch.xml|astra_camera|colorHSV|colorTracker' || true"
sleep 1
docker exec -d "$cid" bash -lc "$ros_setup; ros2 launch astra_camera astra.launch.xml >/tmp/smartcar_astra_camera.log 2>&1"
sleep 2
docker exec -d "$cid" bash -lc "$ros_setup; ros2 run icar_astra colorHSV >/tmp/smartcar_color_hsv.log 2>&1"
docker exec -d "$cid" bash -lc "$ros_setup; ros2 run icar_astra colorTracker --ros-args -r cmd_vel:=/tracking_cmd_vel_shadow -r /cmd_vel:=/tracking_cmd_vel_shadow >/tmp/smartcar_color_tracker.log 2>&1"
echo 'perception-start-issued'
`;
}

function remoteStopPerceptionScript() {
  return `
set +e
${commonContainerLookup()}
cid="$(find_container)"
if [ -n "$cid" ]; then
  docker exec "$cid" bash -lc "pkill -f 'astra.launch.xml|astra_camera|colorHSV|colorTracker' || true"
fi
echo 'perception-stop-issued'
`;
}
