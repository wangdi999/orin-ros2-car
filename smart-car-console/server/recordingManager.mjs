import { spawn } from 'node:child_process';
import { mkdir, readdir, rm, stat, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { bash, redactSensitiveText, shellQuote } from './ssh.mjs';
import { addLog, runtime, updateRecording } from './state.mjs';

const DEFAULT_TOPICS = [
  '/scan',
  '/imu/data_raw',
  '/imu/mag',
  '/voltage',
  '/vel_raw',
  '/joint_states',
  '/tracking_cmd_vel_shadow'
];

export class RecordingManager {
  constructor(sshExecutor, getConfig, recordingsRoot) {
    this.ssh = sshExecutor;
    this.getConfig = getConfig;
    this.recordingsRoot = recordingsRoot;
  }

  async listLocalRecordings() {
    await mkdir(this.recordingsRoot, { recursive: true });
    const entries = await readdir(this.recordingsRoot, { withFileTypes: true });
    const recordings = [];
    for (const entry of entries) {
      if (!entry.isDirectory()) continue;
      const fullPath = path.join(this.recordingsRoot, entry.name);
      const info = await describeDirectory(fullPath);
      recordings.push({
        id: entry.name,
        path: fullPath,
        sizeBytes: info.sizeBytes,
        fileCount: info.fileCount,
        updatedAt: info.updatedAt
      });
    }
    return recordings.toSorted((a, b) => String(b.updatedAt).localeCompare(String(a.updatedAt)));
  }

  async startRecording(topics) {
    const selectedTopics = sanitizeTopics(topics);
    if (selectedTopics.length === 0) {
      return { ok: false, error: 'No ROS topics selected for recording', state: runtime.recording };
    }
    const config = this.getConfig();
    if (!config.car.sshPassword) {
      const error = 'SSH password is not saved; cannot start rosbag recording.';
      updateRecording({ active: false, lastError: error });
      return { ok: false, error, state: runtime.recording };
    }
    if (runtime.recording.active) {
      return { ok: false, error: 'A recording is already active', state: runtime.recording };
    }

    const sessionId = makeSessionId();
    const result = await this.ssh.run(bash(remoteStartRecordingScript(sessionId, selectedTopics)), { timeoutMs: 15000 });
    if (!result.ok) {
      const error = summarizeFailure(result);
      updateRecording({ active: false, sessionId, topics: selectedTopics, lastError: error });
      addLog('error', 'recording', `Start failed: ${error}`);
      return { ok: false, error, state: runtime.recording };
    }

    const remote = parseKeyValue(result.stdout);
    updateRecording({
      active: true,
      sessionId,
      remotePath: remote.REMOTE_PATH || null,
      localPath: null,
      topics: selectedTopics,
      startedAt: new Date().toISOString(),
      stoppedAt: null,
      sizeBytes: 0,
      diskFreeBytes: parseInteger(remote.DISK_FREE_BYTES),
      lastError: null
    });
    addLog('info', 'recording', `Started rosbag recording ${sessionId}`);
    return { ok: true, sessionId, state: runtime.recording };
  }

  async stopRecording() {
    if (!runtime.recording.active || !runtime.recording.sessionId) {
      return { ok: false, error: 'No active recording to stop', state: runtime.recording };
    }

    const sessionId = runtime.recording.sessionId;
    const result = await this.ssh.run(bash(remoteStopRecordingScript(sessionId)), { timeoutMs: 25000 });
    if (!result.ok) {
      const error = summarizeFailure(result);
      updateRecording({ active: false, stoppedAt: new Date().toISOString(), lastError: error });
      addLog('error', 'recording', `Stop failed: ${error}`);
      return { ok: false, error, state: runtime.recording };
    }

    const fields = parseKeyValue(result.stdout);
    const remotePath = fields.HOST_PATH || runtime.recording.remotePath;
    let localPath = null;
    let syncError = null;
    if (remotePath) {
      const sync = await this.syncRemoteRecording(remotePath, sessionId);
      localPath = sync.localPath;
      syncError = sync.error;
    }
    const sizeBytes = localPath ? (await describeDirectory(localPath)).sizeBytes : 0;
    updateRecording({
      active: false,
      sessionId,
      remotePath,
      localPath,
      stoppedAt: new Date().toISOString(),
      sizeBytes,
      lastError: syncError
    });
    addLog(syncError ? 'warn' : 'info', 'recording', syncError ? `Recording stopped but sync failed: ${syncError}` : `Recording ${sessionId} synced locally`);
    return { ok: !syncError, sessionId, localPath, syncError, state: runtime.recording };
  }

  async deleteRecording(id) {
    const safeId = sanitizeId(id);
    if (!safeId) return { ok: false, error: 'Invalid recording id' };
    const fullPath = path.join(this.recordingsRoot, safeId);
    if (!fullPath.startsWith(this.recordingsRoot)) return { ok: false, error: 'Invalid recording path' };
    await rm(fullPath, { recursive: true, force: true });
    return { ok: true };
  }

  async syncRemoteRecording(remotePath, sessionId) {
    await mkdir(this.recordingsRoot, { recursive: true });
    const localPath = path.join(this.recordingsRoot, sessionId);
    await rm(localPath, { recursive: true, force: true });
    await mkdir(localPath, { recursive: true });
    await writeFile(path.join(localPath, 'sync-source.txt'), `${remotePath}\n`, 'utf8');

    const config = this.getConfig();
    const pscpPath = config.car.plinkPath.replace(/plink(\.exe)?$/i, 'pscp$1');
    const args = [
      '-batch',
      '-r',
      '-hostkey',
      config.car.sshHostKey,
      '-pw',
      config.car.sshPassword,
      `${config.car.sshUser}@${config.car.host}:${remotePath}/*`,
      localPath
    ];
    const rawResult = await runProcess(pscpPath, args, 120000);
    const result = {
      ...rawResult,
      stdout: redactSensitiveText(rawResult.stdout, config),
      stderr: redactSensitiveText(rawResult.stderr, config)
    };
    if (!result.ok) {
      return { localPath, error: result.stderr || result.stdout || `pscp exit code ${result.code}` };
    }
    return { localPath, error: null };
  }
}

export function buildTrackingRemapArguments() {
  return ['--ros-args', '-r', 'cmd_vel:=/tracking_cmd_vel_shadow', '-r', '/cmd_vel:=/tracking_cmd_vel_shadow'];
}

export function buildRosbagRecordCommand(sessionId, topics) {
  const safeSessionId = sanitizeId(sessionId);
  const selectedTopics = sanitizeTopics(topics);
  const topicArgs = selectedTopics.map(shellQuote).join(' ');
  return `ros2 bag record -o /root/icar_ros2_ws/temp/smartcar_recordings/${safeSessionId} ${topicArgs}`;
}

function sanitizeTopics(topics) {
  const values = Array.isArray(topics) && topics.length > 0 ? topics : DEFAULT_TOPICS;
  return [...new Set(values.map((topic) => String(topic ?? '').trim()).filter((topic) => /^\/[A-Za-z0-9_][A-Za-z0-9_./-]*$/.test(topic)))];
}

function makeSessionId() {
  return `bag-${new Date().toISOString().replace(/[:.]/g, '-').replace('T', '_').replace('Z', '')}`;
}

function sanitizeId(id) {
  const value = String(id ?? '').trim();
  return /^[A-Za-z0-9_.-]+$/.test(value) ? value : null;
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

function remoteStartRecordingScript(sessionId, topics) {
  const safeSessionId = sanitizeId(sessionId);
  const recordCommand = buildRosbagRecordCommand(safeSessionId, topics);
  return `
set +e
${commonContainerLookup()}
cid="$(find_container)"
if [ -z "$cid" ]; then
  echo 'No running icar container for rosbag recording' >&2
  exit 20
fi
docker exec "$cid" bash -lc "test ! -f /tmp/smartcar_rosbag.pid || ! kill -0 \\$(cat /tmp/smartcar_rosbag.pid) 2>/dev/null" || {
  echo 'A rosbag recording is already active in the car container' >&2
  exit 21
}
docker exec "$cid" bash -lc "mkdir -p /root/icar_ros2_ws/temp/smartcar_recordings && ${rosSetup()}; nohup ${recordCommand} >/tmp/smartcar_rosbag_${safeSessionId}.log 2>&1 & echo \\$! >/tmp/smartcar_rosbag.pid"
printf 'REMOTE_PATH=/root/icar_ros2_ws/temp/smartcar_recordings/%s\\n' '${safeSessionId}'
df -PB1 /home/jetson 2>/dev/null | awk 'NR==2 {printf "DISK_FREE_BYTES=%s\\n", $4}'
`;
}

function remoteStopRecordingScript(sessionId) {
  const safeSessionId = sanitizeId(sessionId);
  return `
set +e
${commonContainerLookup()}
cid="$(find_container)"
if [ -z "$cid" ]; then
  echo 'No running icar container for rosbag recording' >&2
  exit 20
fi
if docker exec "$cid" test -f /tmp/smartcar_rosbag.pid >/dev/null 2>&1; then
  docker exec "$cid" bash -lc "kill -INT \\$(cat /tmp/smartcar_rosbag.pid) 2>/dev/null || true"
  sleep 3
  docker exec "$cid" bash -lc "rm -f /tmp/smartcar_rosbag.pid"
fi
host_base=/home/jetson/temp/smartcar_recordings
mkdir -p "$host_base"
docker cp "$cid:/root/icar_ros2_ws/temp/smartcar_recordings/${safeSessionId}" "$host_base/" >/dev/null 2>&1 || true
printf 'HOST_PATH=%s/%s\\n' "$host_base" '${safeSessionId}'
du -sb "$host_base/${safeSessionId}" 2>/dev/null | awk '{printf "SIZE_BYTES=%s\\n", $1}'
`;
}

async function describeDirectory(root) {
  let sizeBytes = 0;
  let fileCount = 0;
  let updatedAt = null;
  async function walk(dir) {
    const entries = await readdir(dir, { withFileTypes: true });
    for (const entry of entries) {
      const fullPath = path.join(dir, entry.name);
      const info = await stat(fullPath);
      if (entry.isDirectory()) {
        await walk(fullPath);
      } else {
        sizeBytes += info.size;
        fileCount += 1;
        if (!updatedAt || info.mtime > updatedAt) updatedAt = info.mtime;
      }
    }
  }
  await walk(root);
  return {
    sizeBytes,
    fileCount,
    updatedAt: updatedAt?.toISOString() ?? null
  };
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

function parseInteger(value) {
  const number = Number.parseInt(value, 10);
  return Number.isFinite(number) ? number : null;
}

function summarizeFailure(result) {
  if (result.timedOut) return `timeout after ${result.durationMs} ms`;
  return String(result.stderr || result.stdout || `exit code ${result.code}`).trim() || 'unknown error';
}

function runProcess(command, args, timeoutMs) {
  return new Promise((resolve) => {
    let child;
    try {
      child = spawn(command, args, { windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });
    } catch (error) {
      resolve({ ok: false, code: null, stdout: '', stderr: error.message });
      return;
    }
    let stdout = '';
    let stderr = '';
    const timer = setTimeout(() => child.kill('SIGTERM'), timeoutMs);
    child.stdout.on('data', (chunk) => { stdout += chunk.toString('utf8'); });
    child.stderr.on('data', (chunk) => { stderr += chunk.toString('utf8'); });
    child.on('error', (error) => {
      clearTimeout(timer);
      resolve({ ok: false, code: null, stdout, stderr: error.message });
    });
    child.on('close', (code) => {
      clearTimeout(timer);
      resolve({ ok: code === 0, code, stdout, stderr });
    });
  });
}
