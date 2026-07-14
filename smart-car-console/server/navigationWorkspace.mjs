import { randomUUID } from 'node:crypto';
import { bash, shellQuote } from './ssh.mjs';
import {
  normalizeMapId,
  normalizePose,
  serializeRouteYaml,
  validateRoute
} from './navigationProtocol.mjs';

const MAPS_HOST = '/home/jetson/maps';
const MAPS_CONTAINER = '/root/maps';
const ROUTES_HOST = '/home/jetson/routes';
const ROUTES_CONTAINER = '/root/routes';
const MODES = new Set(['safe_base', 'mapping', 'navigation', 'demo']);

export class NavigationWorkspaceManager {
  constructor({ ssh, rosbridge, serviceManager, getConfig, saveConfig, getRuntime, getTelemetry, logger = () => {} }) {
    this.ssh = ssh;
    this.rosbridge = rosbridge;
    this.serviceManager = serviceManager;
    this.getConfig = getConfig;
    this.saveConfig = saveConfig;
    this.getRuntime = getRuntime;
    this.getTelemetry = getTelemetry;
    this.logger = logger;
    this.operation = null;
    this.operationPromises = new Map();
  }

  currentOperation() {
    return this.operation;
  }

  async waitForOperation(operationId) {
    const pending = this.operationPromises.get(operationId);
    if (pending) await pending;
    return this.operation?.operationId === operationId ? this.operation : null;
  }

  startModeSwitch(mode) {
    if (!MODES.has(mode)) throw apiError(400, 'INVALID_MODE', `Unsupported navigation mode: ${mode}`);
    return this.startOperation('MODE_SWITCH', async (update) => {
      update('CANCEL_GOALS', 'Cancelling autonomous goals');
      if (this.rosbridge.connected) await this.rosbridge.callTrigger('/navigation/cancel');
      update('ZERO_VELOCITY', 'Publishing an explicit zero command');
      this.rosbridge.stopManual?.();
      if (mode === 'mapping') {
        update('RESET_MAPPING', 'Clearing the previous mapping session');
        this.rosbridge.resetMappingSession?.();
      }
      update('STOP_OLD_STACK', 'Stopping the previous runtime stack');
      const stopped = await this.serviceManager.stopServices();
      if (stopped?.ok === false) throw new Error(stopped.error || 'Failed to stop previous runtime stack');
      update('SAVE_CONFIG', `Saving ${mode} mode`);
      const current = this.getConfig();
      await this.saveConfig({
        ...current,
        navigation: { ...current.navigation, enabled: true, mode, autoStartPatrol: false }
      });
      update('START_NEW_STACK', `Starting ${mode} runtime stack`);
      const started = await this.serviceManager.startServices();
      if (started?.ok === false) throw new Error(started.error || 'Failed to start new runtime stack');
      return { mode };
    });
  }

  startMapSave(mapId) {
    const id = normalizeMapId(mapId);
    return this.startOperation('MAP_SAVE', async (update) => {
      if (this.getConfig().navigation?.mode !== 'mapping') {
        throw apiError(409, 'MODE_REQUIRED', 'Map saving requires mapping mode', ['MODE_NOT_MAPPING']);
      }
      const map = this.getTelemetry()?.map;
      if (!map?.connected || map?.stale) throw apiError(409, 'MAP_UNAVAILABLE', 'A fresh live Cartographer map is required', ['MAP_NOT_READY']);
      update('ZERO_VELOCITY', 'Publishing an explicit zero command before map save');
      if (!this.rosbridge.stopManual?.()) {
        throw apiError(503, 'STOP_FAILED', 'Map save requires a confirmed zero command', ['ZERO_COMMAND_FAILED']);
      }
      update('SAVE_MAP', `Saving map ${id}`);
      const command = `docker exec smartcar_icar_console /bin/bash -lc ${shellQuote(`. /opt/ros/foxy/setup.bash; . /root/ros2_navigation_overlay/install/setup.bash; ros2 run icar_navigation save_map.sh ${id} ${MAPS_CONTAINER}`)}`;
      await this.runRemote(command, 120000);
      update('VERIFY_MAP', `Verifying map ${id}`);
      const verification = await this.verifyMap(id);
      if (!verification.valid) throw apiError(422, 'MAP_INVALID', verification.message, verification.blockers);
      return { mapId: id, verification };
    });
  }

  async listMaps() {
    const result = await this.runRemote(mapListScript(), 15000);
    return parseMapList(result.stdout, activeMapId(this.getConfig()));
  }

  async verifyMap(mapId) {
    const id = normalizeMapId(mapId);
    const result = await this.runRemote(mapVerificationScript(id), 15000, false);
    const blockers = String(result.stdout || result.stderr).split(/\r?\n/).filter((line) => line.startsWith('BLOCKER=')).map((line) => line.slice(8));
    return {
      mapId: id,
      valid: result.ok && blockers.length === 0,
      blockers,
      message: blockers.length ? blockers.join('; ') : result.ok ? 'Map artifacts are structurally valid' : 'Map verification failed'
    };
  }

  async activateMap(mapId) {
    this.assertNoOperation();
    const mode = this.getConfig().navigation?.mode;
    if (mode === 'navigation' || mode === 'demo') {
      throw apiError(409, 'MODE_SWITCH_REQUIRED', 'Switch to safe_base or mapping before activating a different map', ['NAVIGATION_STACK_RUNNING']);
    }
    this.assertNavigationIdle();
    const id = normalizeMapId(mapId);
    const verification = await this.verifyMap(id);
    if (!verification.valid) throw apiError(422, 'MAP_INVALID', verification.message, verification.blockers);
    const current = this.getConfig();
    await this.saveConfig({
      ...current,
      navigation: {
        ...current.navigation,
        map: `${MAPS_CONTAINER}/${id}.yaml`,
        routeFile: `${ROUTES_CONTAINER}/${id}.yaml`,
        autoStartPatrol: false
      }
    });
    return { mapId: id, active: true };
  }

  async setMapArchived(mapId, archived) {
    this.assertNoOperation();
    this.assertNavigationIdle();
    const id = normalizeMapId(mapId);
    if (archived && id === activeMapId(this.getConfig())) {
      throw apiError(409, 'ACTIVE_MAP', 'The active map cannot be archived', ['MAP_IS_ACTIVE']);
    }
    await this.runRemote(`mkdir -p ${shellQuote(`${MAPS_HOST}/.archive-index`)}\n${archived ? 'touch' : 'rm -f'} ${shellQuote(`${MAPS_HOST}/.archive-index/${id}`)}`);
    return { mapId: id, archived };
  }

  async importActiveMap(mapId) {
    this.assertNoOperation();
    this.assertNavigationIdle();
    const id = normalizeMapId(mapId);
    const source = mapBaseFromConfig(this.getConfig());
    if (!source) throw apiError(409, 'NO_ACTIVE_MAP', 'The current configuration has no importable map');
    const script = importMapScript(source, id);
    await this.runRemote(script, 20000);
    const verification = await this.verifyMap(id);
    if (!verification.valid) throw apiError(422, 'MAP_INVALID', verification.message, verification.blockers);
    return { mapId: id, imported: true, verification };
  }

  async getMapFile(mapId, extension) {
    const id = normalizeMapId(mapId);
    const ext = String(extension).toLowerCase();
    if (!['pgm', 'yaml', 'pbstream'].includes(ext)) throw apiError(400, 'INVALID_EXTENSION', 'Unsupported map file type');
    const result = await this.runRemote(`base64 ${shellQuote(`${MAPS_HOST}/${id}.${ext}`)}`, 20000);
    return { mapId: id, extension: ext, data: Buffer.from(result.stdout.replace(/\s+/g, ''), 'base64') };
  }

  async getMapPreview(mapId) {
    const id = normalizeMapId(mapId);
    const [pgm, yaml] = await Promise.all([this.getMapFile(id, 'pgm'), this.getMapFile(id, 'yaml')]);
    return parseMapPreview(id, pgm.data, yaml.data.toString('utf8'));
  }

  async getRoute(mapId) {
    const id = normalizeMapId(mapId);
    const result = await this.runRemote(routeReadScript(id), 15000, false);
    if (!result.ok || !result.stdout.trim()) return ensureDraftRoute();
    try {
      return validateRoute(JSON.parse(result.stdout));
    } catch {
      throw apiError(422, 'ROUTE_INVALID', 'Stored route is invalid');
    }
  }

  async saveRoute(mapId, route) {
    this.assertNoOperation();
    this.assertNavigationIdle();
    const id = normalizeMapId(mapId);
    const normalized = validateRoute(route);
    const encoded = Buffer.from(serializeRouteYaml(normalized), 'utf8').toString('base64');
    await this.runRemote(routeWriteScript(id, encoded), 15000);
    const mode = this.getConfig().navigation?.mode;
    if (id === activeMapId(this.getConfig()) && ['navigation', 'demo'].includes(mode) && this.rosbridge.connected) {
      const reload = await this.rosbridge.callTrigger('/patrol/reload_route');
      if (reload?.ok === false || reload?.success === false) throw apiError(409, 'ROUTE_RELOAD_FAILED', reload?.message || 'Route saved but reload failed');
    }
    return normalized;
  }

  publishInitialPose(pose) {
    this.assertNoOperation();
    if (this.getConfig().navigation?.mode !== 'navigation') throw apiError(409, 'MODE_REQUIRED', 'Navigation mode is required', ['MODE_NOT_NAVIGATION']);
    if (!activeMapId(this.getConfig())) throw apiError(409, 'ACTIVE_MAP_REQUIRED', 'Activate a managed map first', ['NO_ACTIVE_MAP']);
    if (!this.rosbridge.connected) throw apiError(503, 'ROSBRIDGE_OFFLINE', 'ROSBridge is not connected', ['ROSBRIDGE_OFFLINE']);
    const normalized = normalizePose(pose);
    if (!this.rosbridge.publishInitialPose?.(normalized)) throw apiError(503, 'INITIAL_POSE_FAILED', 'Initial pose could not be published');
    return normalized;
  }

  async sendGoal(pose) {
    this.assertMotionStartAllowed();
    this.assertNavigationIdle();
    if (this.getConfig().navigation?.mode !== 'navigation') throw apiError(409, 'MODE_REQUIRED', 'Navigation mode is required', ['MODE_NOT_NAVIGATION']);
    if (!activeMapId(this.getConfig())) throw apiError(409, 'ACTIVE_MAP_REQUIRED', 'Activate a managed map first', ['NO_ACTIVE_MAP']);
    const localization = this.getTelemetry()?.pose;
    if (!localization?.connected || localization?.stale) throw apiError(409, 'LOCALIZATION_STALE', 'Fresh AMCL/TF localization is required', ['LOCALIZATION_NOT_READY']);
    return this.rosbridge.sendNavigationGoal(normalizePose(pose));
  }

  async cancelGoal() {
    return this.rosbridge.callTrigger('/navigation/cancel');
  }

  assertNavigationIdle() {
    const mode = this.getConfig().navigation?.mode;
    if (!['navigation', 'demo'].includes(mode)) return;
    if (navigationTaskActive(this.getRuntime()?.navigation)) {
      throw apiError(409, 'NAVIGATION_ACTIVE', 'An autonomous navigation task is active', ['ACTIVE_GOAL']);
    }
  }

  assertMotionAcknowledged() {
    if (!this.getConfig().safety?.motionWarningAcknowledgedAt) {
      throw apiError(428, 'MOTION_WARNING_REQUIRED', 'Acknowledge the motion risk warning before starting motion', ['MOTION_WARNING_UNACKNOWLEDGED']);
    }
  }

  assertMotionStartAllowed() {
    this.assertNoOperation();
    this.assertMotionAcknowledged();
  }

  assertNoOperation() {
    if (this.operation?.status === 'RUNNING') {
      throw apiError(409, 'OPERATION_CONFLICT', 'A navigation workflow operation is already running', ['WORKFLOW_OPERATION_RUNNING']);
    }
  }

  async setMotionWarningAcknowledged(acknowledged) {
    const current = this.getConfig();
    const at = acknowledged ? new Date().toISOString() : null;
    await this.saveConfig({ ...current, safety: { ...current.safety, motionWarningAcknowledgedAt: at } });
    return { acknowledged: Boolean(at), acknowledgedAt: at };
  }

  startOperation(type, worker) {
    if (this.operation?.status === 'RUNNING') throw apiError(409, 'OPERATION_CONFLICT', 'A navigation workflow operation is already running');
    const operationId = randomUUID();
    this.operation = { operationId, type, status: 'RUNNING', step: 'QUEUED', message: 'Operation queued', startedAt: new Date().toISOString(), finishedAt: null, result: null, error: null };
    const update = (step, message) => Object.assign(this.operation, { step, message });
    const pending = Promise.resolve().then(() => worker(update)).then((result) => {
      Object.assign(this.operation, { status: 'SUCCEEDED', step: 'DONE', message: 'Operation completed', result, finishedAt: new Date().toISOString() });
    }).catch((error) => {
      Object.assign(this.operation, { status: 'FAILED', step: 'FAILED', message: error.message, error: serializeError(error), finishedAt: new Date().toISOString() });
      this.logger('error', 'navigation-workflow', error.message);
    }).finally(() => this.operationPromises.delete(operationId));
    this.operationPromises.set(operationId, pending);
    return { ...this.operation };
  }

  async runRemote(script, timeoutMs = 15000, throwOnFailure = true) {
    const result = await this.ssh.run(bash(script), { timeoutMs });
    if (!result.ok && throwOnFailure) throw apiError(502, 'REMOTE_COMMAND_FAILED', result.stderr || result.stdout || 'Remote command failed');
    return result;
  }
}

function navigationTaskActive(navigation = {}) {
  const activeStates = new Set(['ACTIVE', 'ACCEPTED', 'EXECUTING', 'CANCELING', 'NAVIGATING', 'WAITING', 'NEXT_GOAL', 'CANCELLING']);
  const states = [navigation?.goal?.state, navigation?.patrol?.state, navigation?.action?.status]
    .map((state) => String(state ?? 'UNKNOWN').toUpperCase());
  const activeGoals = Number(navigation?.action?.activeGoals ?? 0);
  return states.some((state) => activeStates.has(state))
    || (Number.isFinite(activeGoals) && activeGoals > 0);
}

function apiError(statusCode, code, message, blockers = []) {
  const error = new Error(message);
  Object.assign(error, { statusCode, code, blockers });
  return error;
}

function serializeError(error) {
  return { code: error.code || 'OPERATION_FAILED', message: error.message, blockers: error.blockers || [] };
}

function activeMapId(config) {
  const match = String(config?.navigation?.map ?? '').match(/^\/root\/maps\/([A-Za-z0-9_-]{1,64})\.yaml$/);
  return match?.[1] ?? null;
}

function mapBaseFromConfig(config) {
  const value = String(config?.navigation?.map ?? '');
  return value.endsWith('.yaml') ? value.slice(0, -5) : null;
}

function ensureDraftRoute(route = {}) {
  return {
    configured: false,
    frame_id: 'map',
    home: { name: 'Home', x: null, y: null, yaw: null },
    waypoints: [1, 2, 3].map((index) => ({ name: `Waypoint ${index}`, x: null, y: null, yaw: null })),
    default_dwell_sec: 0,
    max_retries: 1,
    failure_policy: 'skip',
    loop: false,
    ...route
  };
}

function mapListScript() {
  return `
set -e
mkdir -p ${shellQuote(MAPS_HOST)} ${shellQuote(`${MAPS_HOST}/.archive-index`)}
for yaml in ${MAPS_HOST}/*.yaml; do
  [ -f "$yaml" ] || continue
  id="$(basename "$yaml" .yaml)"
  archived=0
  [ -f ${shellQuote(`${MAPS_HOST}/.archive-index`)}/"$id" ] && archived=1
  pgm=0; pbstream=0
  [ -s ${shellQuote(MAPS_HOST)}/"$id.pgm" ] && pgm=1
  [ -s ${shellQuote(MAPS_HOST)}/"$id.pbstream" ] && pbstream=1
  printf '%s|%s|%s|%s\n' "$id" "$archived" "$pgm" "$pbstream"
done
`;
}

function parseMapList(text, activeId) {
  return String(text).split(/\r?\n/).filter(Boolean).map((line) => {
    const [id, archived, pgm, pbstream] = line.split('|');
    return {
      id,
      active: id === activeId,
      archived: archived === '1',
      artifacts: { yaml: true, pgm: pgm === '1', pbstream: pbstream === '1' },
      complete: pgm === '1' && pbstream === '1'
    };
  });
}

function mapVerificationScript(id) {
  const base = `${MAPS_HOST}/${id}`;
  return `
set +e
for ext in yaml pgm pbstream; do
  [ -s ${shellQuote(base)}."$ext" ] || printf 'BLOCKER=MISSING_%s\n' "$(printf '%s' "$ext" | tr '[:lower:]' '[:upper:]')"
done
python3 - ${shellQuote(`${base}.yaml`)} ${shellQuote(`${base}.pgm`)} <<'PY'
import pathlib, re, sys
yaml_path, pgm_path = map(pathlib.Path, sys.argv[1:])
if not yaml_path.is_file() or not pgm_path.is_file():
    raise SystemExit(0)
text = yaml_path.read_text(encoding='utf-8', errors='replace')
match = re.search(r'^image:\\s*["\\']?([^"\\'\\s]+)', text, re.M)
if not match or pathlib.Path(match.group(1)).name != pgm_path.name:
    print('BLOCKER=YAML_IMAGE_MISMATCH')
resolution = re.search(r'^resolution:\\s*([0-9.eE+-]+)', text, re.M)
try:
    if not resolution or float(resolution.group(1)) <= 0: print('BLOCKER=INVALID_RESOLUTION')
except ValueError: print('BLOCKER=INVALID_RESOLUTION')
try:
    with pgm_path.open('rb') as stream:
        tokens = []
        while len(tokens) < 4:
            line = stream.readline()
            if not line: break
            line = line.split(b'#', 1)[0]
            tokens.extend(line.split())
        if len(tokens) < 4 or tokens[0] not in (b'P2', b'P5') or int(tokens[1]) <= 0 or int(tokens[2]) <= 0:
            print('BLOCKER=INVALID_PGM')
except Exception:
    print('BLOCKER=INVALID_PGM')
PY
`;
}

function importMapScript(sourceBase, id) {
  const destinationBase = `${MAPS_CONTAINER}/${id}`;
  return `
set -e
mkdir -p ${shellQuote(MAPS_HOST)}
cid="$(docker ps -q --filter name=smartcar_icar_console | head -n 1)"
[ -n "$cid" ] || { echo 'Navigation container is not running' >&2; exit 1; }
for ext in yaml pgm pbstream; do
  docker exec "$cid" test -s ${shellQuote(`${sourceBase}.`)}"$ext"
  docker exec "$cid" cp --no-clobber ${shellQuote(`${sourceBase}.`)}"$ext" ${shellQuote(`${destinationBase}.`)}"$ext"
done
`;
}

function routeReadScript(id) {
  const path = `${ROUTES_HOST}/${id}.yaml`;
  return `
set +e
[ -s ${shellQuote(path)} ] || exit 4
python3 - ${shellQuote(path)} <<'PY'
import json, sys, yaml
with open(sys.argv[1], encoding='utf-8') as stream:
    print(json.dumps(yaml.safe_load(stream), separators=(',', ':')))
PY
`;
}

function routeWriteScript(id, encoded) {
  const target = `${ROUTES_HOST}/${id}.yaml`;
  return `
set -e
mkdir -p ${shellQuote(ROUTES_HOST)}
tmp=${shellQuote(`${target}.tmp`)}.$$
printf '%s' ${shellQuote(encoded)} | base64 -d > "$tmp"
test -s "$tmp"
mv -f "$tmp" ${shellQuote(target)}
`;
}

function parseMapPreview(mapId, pgmBuffer, yamlText) {
  const parsed = parsePgm(pgmBuffer);
  const resolution = Number(yamlText.match(/^resolution:\s*([0-9.eE+-]+)/m)?.[1]);
  const originValues = yamlText.match(/^origin:\s*\[([^\]]+)\]/m)?.[1]?.split(',').map(Number) ?? [];
  const step = Math.max(1, Math.ceil(Math.max(parsed.width, parsed.height) / 320));
  const pixels = [];
  for (let y = 0; y < parsed.height; y += step) {
    const row = [];
    for (let x = 0; x < parsed.width; x += step) row.push(parsed.pixels[y * parsed.width + x]);
    pixels.push(row);
  }
  return {
    mapId,
    width: parsed.width,
    height: parsed.height,
    resolution: Number.isFinite(resolution) ? resolution : null,
    origin: { x: originValues[0] ?? 0, y: originValues[1] ?? 0, yaw: originValues[2] ?? 0 },
    step,
    pixels
  };
}

function parsePgm(buffer) {
  let index = 0;
  const token = () => {
    while (index < buffer.length) {
      if (buffer[index] === 35) while (index < buffer.length && buffer[index] !== 10) index += 1;
      else if (buffer[index] <= 32) index += 1;
      else break;
    }
    const start = index;
    while (index < buffer.length && buffer[index] > 32 && buffer[index] !== 35) index += 1;
    return buffer.subarray(start, index).toString('ascii');
  };
  const magic = token();
  const width = Number(token());
  const height = Number(token());
  const max = Number(token());
  if (!['P2', 'P5'].includes(magic) || !Number.isInteger(width) || width <= 0 || !Number.isInteger(height) || height <= 0 || max <= 0) {
    throw apiError(422, 'INVALID_PGM', 'Map preview is not a valid PGM image');
  }
  let values;
  if (magic === 'P5') {
    if (max > 255) throw apiError(422, 'INVALID_PGM', '16-bit PGM previews are unsupported');
    if (index >= buffer.length || buffer[index] > 32) {
      throw apiError(422, 'INVALID_PGM', 'PGM header is missing the raster separator');
    }
    index += buffer[index] === 13 && buffer[index + 1] === 10 ? 2 : 1;
    values = buffer.subarray(index, index + width * height);
  } else {
    while (index < buffer.length && buffer[index] <= 32) index += 1;
    const body = buffer.subarray(index).toString('ascii').replace(/#[^\n]*/g, '').trim();
    values = Uint8Array.from(body.split(/\s+/).slice(0, width * height).map(Number));
  }
  if (values.length !== width * height) throw apiError(422, 'INVALID_PGM', 'PGM pixel data is incomplete');
  return { width, height, pixels: values };
}
