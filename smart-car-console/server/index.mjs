import { createReadStream, existsSync } from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { WebSocketServer } from 'ws';
import { AlarmManager } from './alarmManager.mjs';
import { CapabilityManager } from './capabilityRegistry.mjs';
import { buildDriveCommand, isZeroTwist, ZERO_TWIST } from './control.mjs';
import { getConfig, loadConfig, mergeApiConfig, publicConfig, saveConfig } from './config.mjs';
import { PerceptionManager } from './perceptionManager.mjs';
import { RecordingManager } from './recordingManager.mjs';
import { NavigationWorkspaceManager } from './navigationWorkspace.mjs';
import { RosbridgeClient } from './rosbridge.mjs';
import { requireJsonContentType, validateLocalRequest } from './requestSecurity.mjs';
import { ServiceManager } from './serviceManager.mjs';
import { SshExecutor } from './ssh.mjs';
import { TelemetryDelivery } from './telemetryDelivery.mjs';
import { publicTopicRegistry } from './topicRegistry.mjs';
import { streamZipDirectory } from './zipDownload.mjs';
import {
  addLog,
  bus,
  clearEmergencyStop,
  configureHeartbeat,
  markCommandStopped,
  markEmergencyStop,
  runtime,
  snapshot,
  telemetry,
  updateCapabilities,
  updateHeartbeat,
  updateVideo
} from './state.mjs';

const rootDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const distDir = path.join(rootDir, 'dist');
const recordingsDir = path.join(rootDir, 'recordings');
const dataDir = path.join(rootDir, 'data');
const apiPort = Number(process.env.SMART_CAR_API_PORT ?? 8787);

await loadConfig();

const rosbridge = new RosbridgeClient(getConfig);
const ssh = new SshExecutor(getConfig, addLog);
const serviceManager = new ServiceManager(ssh, rosbridge, getConfig);
const perceptionManager = new PerceptionManager(ssh, rosbridge, getConfig);
const recordingManager = new RecordingManager(ssh, getConfig, recordingsDir);
const alarmManager = new AlarmManager(path.join(dataDir, 'alarms.json'));
const capabilityManager = new CapabilityManager({
  ssh,
  cachePath: path.join(dataDir, 'capability-cache.json'),
  logger: addLog
});
const navigationWorkspace = new NavigationWorkspaceManager({
  ssh,
  rosbridge,
  serviceManager,
  getConfig,
  saveConfig,
  getRuntime: () => runtime,
  getTelemetry: () => telemetry,
  logger: addLog
});
await alarmManager.load();
updateVideo({ ...getConfig().video, lastConfiguredAt: null });

function isHeartbeatProtectionEnabled() {
  return getConfig().control.heartbeatProtectionEnabled !== false;
}

function heartbeatPayload() {
  return {
    intervalMs: 100,
    timeoutMs: getConfig().control.watchdogMs ?? 500,
    protectionEnabled: isHeartbeatProtectionEnabled()
  };
}

configureHeartbeat(heartbeatPayload());

rosbridge.on('disconnect', () => {
  if (!isHeartbeatProtectionEnabled()) {
    markCommandStopped('ROSBridge disconnected; heartbeat protection disabled');
    configureHeartbeat(heartbeatPayload());
    addLog('warn', 'safety', 'ROSBridge disconnected; heartbeat protection disabled for testing');
    return;
  }
  alarmManager.raise({
    source: 'rosbridge',
    type: 'disconnect',
    severity: 'critical',
    title: 'ROSBridge 断开',
    message: '连接断开，已请求急停',
    dedupeKey: 'rosbridge:disconnect'
  });
  void stopMotion('ROSBridge disconnected');
});

rosbridge.on('car-alarm', (event) => {
  alarmManager.ingestCarAlarm(event);
});

const server = http.createServer(async (req, res) => {
  try {
    const url = new URL(req.url ?? '/', 'http://127.0.0.1');
    if (url.pathname.startsWith('/api/')) {
      const trust = validateLocalRequest(req.headers);
      if (!trust.ok) {
        json(res, trust.statusCode, { ok: false, error: trust.reason });
        return;
      }
      await handleApi(req, res, url);
      return;
    }
    serveStatic(req, res, url);
  } catch (error) {
    addLog('error', 'api', error.message);
    json(res, Number(error.statusCode) || 500, {
      ok: false,
      code: error.code || 'INTERNAL_ERROR',
      message: error.message,
      error: error.message,
      blockers: error.blockers || [],
      state: snapshot()
    });
  }
});

const telemetryWss = new WebSocketServer({ noServer: true });

server.on('upgrade', (req, socket, head) => {
  const url = new URL(req.url ?? '/', 'http://127.0.0.1');
  const trust = validateLocalRequest(req.headers);
  if (url.pathname !== '/api/telemetry' || !trust.ok) {
    socket.destroy();
    return;
  }
  telemetryWss.handleUpgrade(req, socket, head, (ws) => {
    telemetryWss.emit('connection', ws, req);
  });
});

telemetryWss.on('connection', (ws) => {
  const delivery = new TelemetryDelivery(ws);
  delivery.sendInitialSnapshot(snapshot());
  const onSnapshot = (data) => {
    delivery.queueSnapshot(data);
  };
  const onLog = (entry) => {
    delivery.queueLog(entry);
  };
  const onTelemetry = (data) => {
    delivery.queueTelemetry(data);
  };
  const onRuntimePatch = (data) => {
    delivery.queueRuntimePatch(data);
  };
  bus.on('snapshot', onSnapshot);
  bus.on('log', onLog);
  bus.on('telemetry', onTelemetry);
  bus.on('runtime-patch', onRuntimePatch);
  ws.on('close', () => {
    delivery.close();
    bus.off('snapshot', onSnapshot);
    bus.off('log', onLog);
    bus.off('telemetry', onTelemetry);
    bus.off('runtime-patch', onRuntimePatch);
    if (isHeartbeatProtectionEnabled()) {
      alarmManager.raise({
        source: 'ui',
        type: 'telemetry_disconnect',
        severity: 'critical',
        title: '控制台遥测断开',
        message: '浏览器遥测 WebSocket 已断开',
        dedupeKey: 'ui:telemetry_disconnect'
      });
      void stopMotion('Telemetry WebSocket disconnected');
      return;
    }
    markCommandStopped('Telemetry WebSocket disconnected; heartbeat protection disabled');
    configureHeartbeat(heartbeatPayload());
    addLog('warn', 'safety', 'Telemetry WebSocket disconnected; heartbeat protection disabled for testing');
  });
});

server.listen(apiPort, '127.0.0.1', () => {
  addLog('info', 'api', `Smart car API listening on http://127.0.0.1:${apiPort}`);
  rosbridge.connect();
  void Promise.all([
    serviceManager.refreshStatus(),
    capabilityManager.refresh().then(updateCapabilities)
  ]);
});

setInterval(() => {
  if (!isHeartbeatProtectionEnabled()) return;
  const watchdogMs = getConfig().control.watchdogMs ?? 500;
  if (!runtime.command.active || !runtime.command.lastDriveAt) return;
  const heartbeatAt = Date.parse(runtime.command.heartbeat.lastAt);
  const lastSignalAt = Math.max(
    runtime.command.lastDriveAt,
    Number.isFinite(heartbeatAt) ? heartbeatAt : 0
  );
  if (Date.now() - lastSignalAt > watchdogMs) {
    alarmManager.raise({
      source: 'safety',
      type: 'watchdog_timeout',
      severity: 'critical',
      title: '遥控心跳超时',
      message: `超过 ${watchdogMs} ms 未收到有效遥控/心跳`,
      dedupeKey: 'safety:watchdog_timeout'
    });
    void stopMotion('Drive watchdog timeout');
  }
}, 100);

setInterval(() => {
  alarmManager.evaluate();
}, 1000);

process.on('SIGINT', async () => {
  await stopMotion('API process interrupted');
  process.exit(0);
});

async function handleApi(req, res, url) {
  if (req.method === 'POST' && url.pathname === '/api/navigation/mode') {
    const body = await readJson(req);
    const operation = navigationWorkspace.startModeSwitch(String(body.mode ?? ''));
    json(res, 202, response('OPERATION_ACCEPTED', 'Mode switch accepted', { operationId: operation.operationId, operation, state: snapshot() }));
    return;
  }
  if (req.method === 'GET' && url.pathname === '/api/navigation/operations/current') {
    json(res, 200, response('OK', 'Navigation operation state', { operation: navigationWorkspace.currentOperation(), state: snapshot() }));
    return;
  }
  if (req.method === 'GET' && url.pathname === '/api/maps') {
    const maps = await navigationWorkspace.listMaps();
    json(res, 200, response('OK', 'Managed maps', { maps, state: snapshot() }));
    return;
  }
  if (req.method === 'POST' && url.pathname === '/api/maps/save') {
    const body = await readJson(req);
    const operation = navigationWorkspace.startMapSave(body.name ?? body.mapId);
    json(res, 202, response('OPERATION_ACCEPTED', 'Map save accepted', { operationId: operation.operationId, operation, state: snapshot() }));
    return;
  }
  if (req.method === 'POST' && url.pathname === '/api/maps/import-active') {
    const body = await readJson(req);
    const result = await navigationWorkspace.importActiveMap(body.name ?? body.mapId);
    json(res, 200, response('MAP_IMPORTED', 'Active map imported into managed storage', { result, state: snapshot() }));
    return;
  }
  const mapActionMatch = url.pathname.match(/^\/api\/maps\/([^/]+)\/(verify|activate|archive|restore)$/);
  if (req.method === 'POST' && mapActionMatch) {
    const mapId = decodeURIComponent(mapActionMatch[1]);
    const action = mapActionMatch[2];
    const result = action === 'verify'
      ? await navigationWorkspace.verifyMap(mapId)
      : action === 'activate'
        ? await navigationWorkspace.activateMap(mapId)
        : await navigationWorkspace.setMapArchived(mapId, action === 'archive');
    const statusCode = result.valid === false ? 422 : 200;
    json(res, statusCode, response(result.valid === false ? 'MAP_INVALID' : 'OK', result.message || `Map ${action} completed`, {
      ok: statusCode < 400,
      result,
      state: snapshot(),
      blockers: result.blockers || []
    }));
    return;
  }
  const mapPreviewMatch = url.pathname.match(/^\/api\/maps\/([^/]+)\/preview$/);
  if (req.method === 'GET' && mapPreviewMatch) {
    const preview = await navigationWorkspace.getMapPreview(decodeURIComponent(mapPreviewMatch[1]));
    json(res, 200, response('OK', 'Map preview', { preview, state: snapshot() }));
    return;
  }
  const mapFileMatch = url.pathname.match(/^\/api\/maps\/([^/]+)\/files\/(pgm|yaml|pbstream)$/);
  if (req.method === 'GET' && mapFileMatch) {
    const file = await navigationWorkspace.getMapFile(decodeURIComponent(mapFileMatch[1]), mapFileMatch[2]);
    res.writeHead(200, {
      'content-type': file.extension === 'yaml' ? 'application/yaml; charset=utf-8' : 'application/octet-stream',
      'content-disposition': `attachment; filename="${file.mapId}.${file.extension}"`,
      'cache-control': 'no-store'
    });
    res.end(file.data);
    return;
  }
  const routeMatch = url.pathname.match(/^\/api\/routes\/([^/]+)$/);
  if (routeMatch && req.method === 'GET') {
    const route = await navigationWorkspace.getRoute(decodeURIComponent(routeMatch[1]));
    json(res, 200, response('OK', 'Map route', { route, state: snapshot() }));
    return;
  }
  if (routeMatch && req.method === 'PUT') {
    const route = await navigationWorkspace.saveRoute(decodeURIComponent(routeMatch[1]), await readJson(req));
    json(res, 200, response('ROUTE_SAVED', 'Route saved and reloaded', { route, state: snapshot() }));
    return;
  }
  if (req.method === 'POST' && url.pathname === '/api/localization/initial-pose') {
    const pose = navigationWorkspace.publishInitialPose(await readJson(req));
    json(res, 200, response('INITIAL_POSE_PUBLISHED', 'Initial pose published', { pose, state: snapshot() }));
    return;
  }
  if (req.method === 'POST' && url.pathname === '/api/navigation/goals') {
    const result = await navigationWorkspace.sendGoal(await readJson(req));
    const statusCode = result?.ok === false ? 503 : result?.accepted === false || result?.success === false ? 409 : 202;
    json(res, statusCode, response(statusCode === 202 ? 'GOAL_ACCEPTED' : 'GOAL_REJECTED', result?.message || 'Navigation goal processed', {
      ok: statusCode < 400,
      result,
      state: snapshot()
    }));
    return;
  }
  if (req.method === 'DELETE' && url.pathname === '/api/navigation/goals/current') {
    const result = await navigationWorkspace.cancelGoal();
    const statusCode = result?.ok === false ? 503 : result?.success === false ? 409 : 200;
    json(res, statusCode, response(statusCode === 200 ? 'GOAL_CANCELLED' : 'GOAL_CANCEL_FAILED', result?.message || 'Navigation cancellation requested', {
      ok: statusCode < 400,
      result,
      state: snapshot()
    }));
    return;
  }
  if (req.method === 'POST' && url.pathname === '/api/safety/motion-warning/ack') {
    const result = await navigationWorkspace.setMotionWarningAcknowledged(true);
    json(res, 200, response('MOTION_WARNING_ACKNOWLEDGED', 'Motion warning acknowledged', { result, config: publicConfig(), state: snapshot() }));
    return;
  }
  if (req.method === 'DELETE' && url.pathname === '/api/safety/motion-warning/ack') {
    const result = await navigationWorkspace.setMotionWarningAcknowledged(false);
    json(res, 200, response('MOTION_WARNING_RESET', 'Motion warning acknowledgement reset', { result, config: publicConfig(), state: snapshot() }));
    return;
  }
  if (req.method === 'GET' && url.pathname === '/api/config') {
    json(res, 200, { ok: true, config: publicConfig() });
    return;
  }
  if (req.method === 'POST' && url.pathname === '/api/config') {
    const body = await readJson(req);
    const current = getConfig();
    const next = mergeApiConfig(current, body);
    await saveConfig(next);
    updateVideo({ ...next.video, lastConfiguredAt: new Date().toISOString() });
    configureHeartbeat(heartbeatPayload());
    addLog('info', 'config', `Saved connection settings for ${next.car.sshUser}@${next.car.host}`);
    rosbridge.close();
    setTimeout(() => rosbridge.connect(), 250);
    json(res, 200, { ok: true, config: publicConfig() });
    return;
  }
  if (req.method === 'GET' && url.pathname === '/api/status') {
    const [, capabilities] = await Promise.all([
      serviceManager.refreshStatus(),
      capabilityManager.refresh()
    ]);
    updateCapabilities(capabilities);
    json(res, 200, { ok: true, config: publicConfig(), state: snapshot() });
    return;
  }
  if (req.method === 'GET' && url.pathname === '/api/capabilities') {
    const capabilities = url.searchParams.get('refresh') === '1'
      ? await capabilityManager.refresh({ force: true })
      : capabilityManager.get();
    updateCapabilities(capabilities);
    json(res, 200, { ok: true, capabilities });
    return;
  }
  if (req.method === 'GET' && url.pathname === '/api/topic-registry') {
    json(res, 200, { ok: true, topics: publicTopicRegistry() });
    return;
  }
  if (req.method === 'GET' && url.pathname === '/api/alarms') {
    json(res, 200, {
      ok: true,
      alarms: alarmManager.list({
        status: url.searchParams.get('status'),
        severity: url.searchParams.get('severity')
      })
    });
    return;
  }
  const alarmMatch = url.pathname.match(/^\/api\/alarms\/([^/]+)\/(ack|resolve)$/);
  if (req.method === 'POST' && alarmMatch) {
    const alarm = alarmMatch[2] === 'ack'
      ? alarmManager.ack(decodeURIComponent(alarmMatch[1]))
      : alarmManager.resolve(decodeURIComponent(alarmMatch[1]));
    json(res, alarm ? 200 : 404, alarm ? { ok: true, alarm, state: snapshot() } : { ok: false, error: 'Alarm not found' });
    return;
  }
  if (req.method === 'POST' && url.pathname === '/api/video/config') {
    const body = await readJson(req);
    const current = getConfig();
    const next = {
      ...current,
      video: {
        ...current.video,
        ...body.video
      }
    };
    await saveConfig(next);
    updateVideo({ ...next.video, lastConfiguredAt: new Date().toISOString() });
    addLog('info', 'video', `Saved MJPEG config ${next.video.width}x${next.video.height}@${next.video.fps}`);
    json(res, 200, { ok: true, config: publicConfig(), state: snapshot() });
    return;
  }
  if (req.method === 'GET' && url.pathname === '/api/perception/status') {
    await perceptionManager.refreshStatus();
    json(res, 200, { ok: true, perception: runtime.perception, recording: runtime.recording, state: snapshot() });
    return;
  }
  if (req.method === 'POST' && url.pathname === '/api/telemetry/preview') {
    const body = await readJson(req);
    rosbridge.setPerceptionPreviewEnabled(body.enabled === true);
    json(res, 200, {
      ok: true,
      enabled: body.enabled === true,
      state: snapshot()
    });
    return;
  }
  if (req.method === 'POST' && url.pathname === '/api/perception/start') {
    const result = await perceptionManager.startPerception();
    json(res, result.ok ? 200 : 500, { ...result, state: snapshot() });
    return;
  }
  if (req.method === 'POST' && url.pathname === '/api/perception/stop') {
    const result = await perceptionManager.stopPerception();
    json(res, result.ok ? 200 : 500, { ...result, state: snapshot() });
    return;
  }
  if (req.method === 'GET' && url.pathname === '/api/recordings') {
    const recordings = await recordingManager.listLocalRecordings();
    json(res, 200, { ok: true, recordings, recording: runtime.recording });
    return;
  }
  if (req.method === 'POST' && url.pathname === '/api/recordings/start') {
    const body = await readJson(req);
    const result = await recordingManager.startRecording(body.topics);
    json(res, result.ok ? 200 : 500, { ...result, state: snapshot() });
    return;
  }
  if (req.method === 'POST' && url.pathname === '/api/recordings/stop') {
    const result = await recordingManager.stopRecording();
    json(res, result.ok ? 200 : 500, { ...result, state: snapshot() });
    return;
  }
  const recordingMatch = url.pathname.match(/^\/api\/recordings\/([^/]+)(?:\/download)?$/);
  if (recordingMatch && req.method === 'DELETE') {
    const result = await recordingManager.deleteRecording(decodeURIComponent(recordingMatch[1]));
    json(res, result.ok ? 200 : 400, result);
    return;
  }
  if (recordingMatch && req.method === 'GET' && url.pathname.endsWith('/download')) {
    await downloadRecording(res, decodeURIComponent(recordingMatch[1]));
    return;
  }
  if (req.method === 'POST' && url.pathname === '/api/services/start') {
    const config = getConfig();
    if (!config.car.sshPassword) {
      const message = 'SSH password is not saved; save the car SSH password in connection settings before starting services.';
      addLog('error', 'ssh', message);
      json(res, 400, { ok: false, code: 'SSH_PASSWORD_REQUIRED', error: message, config: publicConfig(), state: snapshot() });
      return;
    }
    if (!runtime.status.ssh.connected) {
      addLog('info', 'ssh', `SSH is not connected; trying ${config.car.sshUser}@${config.car.host} with the saved password`);
    }
    const result = await serviceManager.startServices();
    json(res, result.ok ? 200 : 500, { ...result, state: snapshot() });
    return;
  }
  if (req.method === 'POST' && url.pathname === '/api/services/stop') {
    await emergencyStop('Stop services requested');
    const result = await serviceManager.stopServices();
    json(res, result.ok ? 200 : 500, { ...result, state: snapshot() });
    return;
  }
  if (req.method === 'POST' && url.pathname === '/api/emergency-stop') {
    const stopped = await emergencyStop('Emergency stop requested');
    json(res, stopped ? 200 : 503, { ok: stopped, state: snapshot() });
    return;
  }
  if (req.method === 'POST' && (
    url.pathname === '/api/control/resume' || url.pathname === '/api/safety/reset'
  )) {
    const result = await resetSafety();
    json(res, result.ok ? 200 : 409, { ...result, state: snapshot() });
    return;
  }
  const triggerServices = new Map([
    ['/api/safety/simulate-low-battery', '/safety/simulate_low_battery'],
    ['/api/patrol/start', '/patrol/start'],
    ['/api/patrol/cancel', '/patrol/cancel'],
    ['/api/patrol/return-home', '/patrol/return_home']
  ]);
  if (req.method === 'POST' && triggerServices.has(url.pathname)) {
    if (url.pathname !== '/api/patrol/cancel') navigationWorkspace.assertMotionStartAllowed();
    const result = await rosbridge.callTrigger(triggerServices.get(url.pathname));
    const statusCode = result.success ? 200 : result.ok ? 409 : 503;
    json(res, statusCode, { ...result, state: snapshot() });
    return;
  }
  if (req.method === 'POST' && url.pathname === '/api/heartbeat') {
    updateHeartbeat(heartbeatPayload());
    json(res, 200, { ok: true, heartbeat: runtime.command.heartbeat });
    return;
  }
  if (req.method === 'POST' && url.pathname === '/api/drive') {
    const body = await readJson(req);
    const { twist, straightAssist } = buildDriveCommand(body, getConfig().control, telemetry.velocity);
    if (isZeroTwist(twist)) {
      const stopped = await stopMotion('Joystick released');
      json(res, stopped ? 200 : 503, { ok: stopped, twist: ZERO_TWIST, state: snapshot() });
      return;
    }
    navigationWorkspace.assertMotionStartAllowed();
    if (!runtime.status.canDrive) {
      json(res, 409, {
        ok: false,
        error: 'Drive disabled until required devices and ROSBridge are connected',
        blockers: runtime.status.blockers,
        state: snapshot()
      });
      return;
    }
    if (runtime.safety.emergencyStopActive) {
      json(res, 423, {
        ok: false,
        error: 'Emergency stop is active; resume control before sending motion commands',
        state: snapshot()
      });
      return;
    }
    if (!rosbridge.connected || !rosbridge.publishTwist(twist)) {
      json(res, 409, {
        ok: false,
        error: 'ROSBridge is not connected',
        state: snapshot()
      });
      return;
    }
    runtime.command.lastDriveAt = Date.now();
    runtime.command.active = true;
    runtime.command.lastTwist = twist;
    updateHeartbeat(heartbeatPayload());
    runtime.command.straightAssist = {
      ...straightAssist,
      updatedAt: new Date().toISOString()
    };
    clearEmergencyStop();
    json(res, 200, { ok: true, twist, state: snapshot() });
    return;
  }
  if (req.method === 'GET' && url.pathname === '/api/video') {
    proxyVideo(req, res);
    return;
  }
  json(res, 404, { ok: false, error: 'Not found' });
}

async function downloadRecording(res, id) {
  const safeId = String(id ?? '').trim();
  if (!/^[A-Za-z0-9_.-]+$/.test(safeId)) {
    json(res, 400, { ok: false, error: 'Invalid recording id' });
    return;
  }
  const recordingPath = path.join(recordingsDir, safeId);
  if (!recordingPath.startsWith(recordingsDir) || !existsSync(recordingPath)) {
    json(res, 404, { ok: false, error: 'Recording not found' });
    return;
  }
  try {
    await streamZipDirectory(recordingPath, safeId, res);
  } catch (error) {
    if (!res.headersSent) json(res, 500, { ok: false, error: error.message });
    else res.end();
  }
}

async function emergencyStop(reason) {
  markEmergencyStop(reason);
  alarmManager.raise({
    source: 'safety',
    type: 'emergency_stop',
    severity: 'critical',
    title: '急停已触发',
    message: reason,
    dedupeKey: 'safety:emergency_stop'
  });
  const sentOverRosbridge = rosbridge.emergencyStop();
  if (!sentOverRosbridge) {
    const fallbackOk = await serviceManager.emergencyStopFallback(reason);
    return fallbackOk;
  }
  addLog('warn', 'safety', reason);
  return true;
}

async function resetSafety() {
  snapshot();
  if (!rosbridge.connected) {
    return {
      ok: false,
      error: 'ROSBridge is not connected',
      blockers: ['ROSBridge is not connected']
    };
  }
  const stopped = rosbridge.stopManual(2);
  if (!stopped) {
    return { ok: false, error: 'Failed to publish zero Twist before resuming control' };
  }
  const result = await rosbridge.resetSafety();
  if (!result.success) {
    addLog('warn', 'safety', `Safety reset rejected: ${result.message}`);
    return {
      ok: false,
      success: false,
      error: result.message,
      service: result.service ?? '/safety/reset'
    };
  }
  markCommandStopped('Control resumed');
  clearEmergencyStop();
  const localEstopAlarm = alarmManager.list().items.find(
    (item) => item.dedupeKey === 'safety:emergency_stop'
      && item.status !== 'resolved'
  );
  if (localEstopAlarm) alarmManager.resolve(localEstopAlarm.id);
  updateHeartbeat(heartbeatPayload());
  addLog('info', 'safety', 'Safety reset accepted after zero Twist confirmation');
  return { ok: true, success: true, message: result.message };
}

async function stopMotion(reason) {
  markCommandStopped(reason);
  alarmManager.raise({
    source: 'safety',
    type: 'motion_stop',
    severity: 'info',
    title: '运动命令归零',
    message: reason,
    dedupeKey: 'safety:motion_stop'
  });
  const sentOverRosbridge = rosbridge.stopManual(3);
  if (!sentOverRosbridge) {
    return serviceManager.emergencyStopFallback(reason);
  }
  addLog('info', 'safety', reason);
  return true;
}

function proxyVideo(req, res) {
  const upstream = http.get(`http://${getConfig().car.host}:6500/video_feed`, (upstreamRes) => {
    res.writeHead(upstreamRes.statusCode ?? 200, {
      'content-type': upstreamRes.headers['content-type'] ?? 'multipart/x-mixed-replace; boundary=frame',
      'cache-control': 'no-store'
    });
    upstreamRes.pipe(res);
  });
  upstream.on('error', (error) => {
    addLog('warn', 'video', `Video proxy failed: ${error.message}`);
    if (!res.headersSent) {
      json(res, 502, { ok: false, error: error.message });
    } else {
      res.end();
    }
  });
  req.on('close', () => upstream.destroy());
}

function serveStatic(req, res, url) {
  const pathname = url.pathname === '/' ? '/index.html' : url.pathname;
  const filePath = path.join(distDir, pathname);
  if (!filePath.startsWith(distDir) || !existsSync(filePath)) {
    res.writeHead(404, { 'content-type': 'text/plain; charset=utf-8' });
    res.end('Run npm run dev for the Vite UI, or npm run build before serving statically.');
    return;
  }
  const ext = path.extname(filePath);
  const type = {
    '.html': 'text/html; charset=utf-8',
    '.js': 'text/javascript; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.svg': 'image/svg+xml'
  }[ext] ?? 'application/octet-stream';
  res.writeHead(200, { 'content-type': type });
  createReadStream(filePath).pipe(res);
}

function readJson(req) {
  requireJsonContentType(req.headers);
  return new Promise((resolve, reject) => {
    let body = '';
    req.on('data', (chunk) => {
      body += chunk.toString('utf8');
      if (body.length > 128_000) {
        reject(new Error('Request body too large'));
        req.destroy();
      }
    });
    req.on('end', () => {
      if (!body) {
        resolve({});
        return;
      }
      try {
        resolve(JSON.parse(body));
      } catch (error) {
        reject(error);
      }
    });
    req.on('error', reject);
  });
}

function json(res, statusCode, payload) {
  res.writeHead(statusCode, {
    'content-type': 'application/json; charset=utf-8',
    'cache-control': 'no-store'
  });
  res.end(JSON.stringify(payload));
}

function response(code, message, fields = {}) {
  return {
    ok: true,
    code,
    message,
    blockers: fields.blockers || [],
    ...fields
  };
}
