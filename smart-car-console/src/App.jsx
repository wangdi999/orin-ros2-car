import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  DRIVE_PUBLISH_INTERVAL_MS,
  HEARTBEAT_INTERVAL_MS,
  JOYSTICK_ALPHA,
  WATCHDOG_TIMEOUT_MS,
  hasMotion,
  smoothJoystickVector
} from './driveSmoothing.js';
import { keyboardVectorFromCodes, isDriveKeyCode } from './keyboardDrive.js';
import { capabilityUiState, visibleCapabilityItems } from './capabilityViewModel.js';

const emptyState = {
  runtime: {
    capabilities: {
      schemaVersion: 1,
      target: 'X3',
      groups: [],
      detectedAt: null,
      stale: true,
      error: '能力尚未探测',
      items: {}
    },
    topicActivity: {},
    rosbridge: { connected: false, url: null, lastError: null },
    status: {
      ssh: { connected: false, hostname: null },
      devices: {
        chassisSerial: false,
        lidar: false,
        cameraDepth: false,
        cameraUvc: false,
        video0: false
      },
      ports: { control6000: false, video6500: false, rosbridge9090: false },
      services: {
        docker: false,
        container: null,
        chassis: false,
        lidar: false,
        camera: false,
        rosbridge: false,
        video: false
      },
      canDrive: false,
      blockers: ['等待状态检查'],
      updatedAt: null
    },
    logs: [],
    safety: { emergencyStopActive: false, lastStopReason: null },
    navigation: {
      activeSource: 'UNKNOWN',
      safetyState: 'UNKNOWN',
      chassisConnected: false,
      patrol: {
        state: 'UNKNOWN',
        mode: null,
        waypoint: null,
        index: null,
        attempt: null,
        routeConfigured: false,
        reason: null
      },
      action: { status: 'UNKNOWN', activeGoals: 0, updatedAt: null },
      lastService: null,
      updatedAt: null
    },
    command: {
      active: false,
      lastTwist: null,
      heartbeat: {
        connected: false,
        lastAt: null,
        ageMs: null,
        intervalMs: HEARTBEAT_INTERVAL_MS,
        timeoutMs: WATCHDOG_TIMEOUT_MS,
        protectionEnabled: true
      },
      straightAssist: {
        enabled: false,
        active: false,
        reason: null,
        feedbackAngular: null,
        feedbackAgeMs: null,
        correctionAngular: 0,
        updatedAt: null
      }
    },
    perception: {
      services: {
        astraCamera: false,
        colorHsv: false,
        colorTracker: false
      },
      topicDiscovery: {
        discoveredAt: null,
        topics: [],
        matches: {}
      },
      lastError: null,
      updatedAt: null
    },
    recording: {
      active: false,
      sessionId: null,
      remotePath: null,
      localPath: null,
      topics: [],
      startedAt: null,
      stoppedAt: null,
      sizeBytes: 0,
      diskFreeBytes: null,
      lastError: null,
      updatedAt: null
    },
    video: {
      width: 640,
      height: 480,
      fps: 20,
      jpegQuality: 70,
      latencyTargetMs: 100,
      lastConfiguredAt: null
    },
    alarms: {
      items: [],
      summary: { total: 0, active: 0, acknowledged: 0, resolved: 0, critical: 0, warning: 0 },
      updatedAt: null
    }
  },
  telemetry: {
    lidar: { connected: false, rangeMax: 12, points: [] },
    map: {
      connected: false,
      mode: null,
      width: null,
      height: null,
      previewWidth: null,
      previewHeight: null,
      resolution: null,
      origin: { x: null, y: null, yaw: null },
      cells: []
    },
    globalCostmap: { connected: false, cells: [] },
    localCostmap: { connected: false, cells: [] },
    globalPath: { connected: false, empty: true, points: [] },
    localPath: { connected: false, empty: true, points: [] },
    patrolRoute: { connected: false, empty: true, points: [] },
    pose: {
      connected: false,
      pose: { x: null, y: null, yaw: null },
      linear: null,
      angular: null
    },
    imu: {
      connected: false,
      orientation: { yaw: null, roll: null, pitch: null },
      acceleration: { x: null, y: null, z: null },
      gyro: { x: null, y: null, z: null },
      magnetometer: { x: null, y: null, z: null }
    },
    voltage: { connected: false, battery: null, rawBattery: null, percent: null, percentEstimated: true, invalidReason: null },
    velocity: { connected: false, linear: null, angular: null },
    camera: {
      connected: false,
      topic: null,
      type: null,
      previewType: null,
      dataUrl: null,
      width: null,
      height: null,
      encoding: null,
      pixels: []
    },
    depth: {
      connected: false,
      topic: null,
      type: null,
      previewType: null,
      width: null,
      height: null,
      encoding: null,
      min: null,
      max: null,
      values: []
    },
    ir: {
      connected: false,
      topic: null,
      type: null,
      previewType: null,
      width: null,
      height: null,
      encoding: null,
      min: null,
      max: null,
      values: []
    },
    pointCloud: {
      connected: false,
      topic: null,
      type: null,
      frameId: null,
      totalPoints: 0,
      sampledPoints: 0,
      bounds: null,
      points: []
    },
    tracking: {
      connected: false,
      imageTopic: null,
      velocityTopic: '/tracking_cmd_vel_shadow',
      image: null,
      shadowTwist: null
    },
    detections: {
      connected: false,
      topic: null,
      type: null,
      sourceWidth: 640,
      sourceHeight: 480,
      count: 0,
      detections: []
    }
  }
};

const defaultConfig = {
  car: {
    host: '192.168.43.137',
    sshUser: 'jetson',
    sshPasswordSet: false,
    sshHostKeySet: false,
    plinkConfigured: false
  },
  control: {
    maxLinearMps: 0.05,
    maxAngularRps: 0.2,
    turnScale: -1,
    deadZone: 0.05,
    watchdogMs: WATCHDOG_TIMEOUT_MS,
    heartbeatProtectionEnabled: true,
    straightAssist: {
      enabled: true,
      feedbackSign: -1,
      gain: 0.5,
      maxCorrectionRps: 0.25,
      feedbackDeadZoneRps: 0.02,
      feedbackMaxAgeMs: 600,
      minForwardInput: 0.2
    }
  },
  video: {
    width: 640,
    height: 480,
    fps: 20,
    jpegQuality: 70,
    latencyTargetMs: 100
  }
};

const TELEMETRY_STALE_MS = 5000;
const DEFAULT_RECORD_TOPICS = ['/scan', '/imu/data_raw', '/imu/mag', '/voltage', '/vel_raw', '/tracking_cmd_vel_shadow'];

function mergeTelemetryPatch(previous, patch = {}) {
  const telemetry = { ...previous.telemetry };
  for (const [key, value] of Object.entries(patch)) {
    telemetry[key] = { ...(telemetry[key] ?? {}), ...value };
  }
  return { ...previous, telemetry };
}

function mergeRuntimePatch(previous, patch = {}) {
  const runtime = { ...previous.runtime, ...patch };
  if (patch.status) runtime.status = { ...previous.runtime.status, ...patch.status };
  if (patch.command) {
    runtime.command = { ...previous.runtime.command, ...patch.command };
    if (patch.command.heartbeat) {
      runtime.command.heartbeat = { ...previous.runtime.command.heartbeat, ...patch.command.heartbeat };
    }
  }
  if (patch.topicActivity) {
    runtime.topicActivity = { ...previous.runtime.topicActivity, ...patch.topicActivity };
  }
  return { ...previous, runtime };
}

function appendLog(previous, entry) {
  const logs = [...(previous.runtime.logs ?? []).filter((item) => item.id !== entry.id), entry].slice(-240);
  return { ...previous, runtime: { ...previous.runtime, logs } };
}

export default function App() {
  const [state, setState] = useState(emptyState);
  const [config, setConfig] = useState(defaultConfig);
  const [connection, setConnection] = useState('connecting');
  const [busy, setBusy] = useState(null);
  const [configOpen, setConfigOpen] = useState(false);
  const [activeSection, setActiveSection] = useState('overview');
  const [linearLimit, setLinearLimit] = useState(0.05);
  const [angularLimit, setAngularLimit] = useState(0.2);
  const [driveVector, setDriveVector] = useState({ forward: 0, turn: 0, strafe: 0 });
  const [keyboardActive, setKeyboardActive] = useState(false);
  const [recordings, setRecordings] = useState([]);
  const sendDriveRef = useRef({ lastSent: 0, pending: null });
  const pressedKeysRef = useRef(new Set());
  const targetDriveRef = useRef({ forward: 0, turn: 0, strafe: 0 });
  const smoothedDriveRef = useRef({ forward: 0, turn: 0, strafe: 0 });

  const status = state.runtime.status;
  const telemetry = state.telemetry;
  const logs = state.runtime.logs;
  const perception = state.runtime.perception ?? emptyState.runtime.perception;
  const recording = state.runtime.recording ?? emptyState.runtime.recording;
  const alarms = state.runtime.alarms ?? emptyState.runtime.alarms;
  const video = state.runtime.video ?? config.video ?? defaultConfig.video;
  const safety = state.runtime.safety ?? emptyState.runtime.safety;
  const navigation = state.runtime.navigation ?? emptyState.runtime.navigation;
  const capabilities = state.runtime.capabilities ?? emptyState.runtime.capabilities;
  const driveReady = status.canDrive && connection === 'connected' && !busy;
  const canDrive = driveReady && !safety.emergencyStopActive;

  useEffect(() => {
    setLinearLimit((value) => Math.min(value, config.control.maxLinearMps));
    setAngularLimit((value) => Math.min(value, config.control.maxAngularRps));
  }, [config.control.maxAngularRps, config.control.maxLinearMps]);

  const refreshStatus = useCallback(async () => {
    const response = await fetch('/api/status', { cache: 'no-store' });
    const payload = await response.json();
    if (payload.config) setConfig(payload.config);
    if (payload.state) setState(payload.state);
  }, []);

  const refreshPerception = useCallback(async () => {
    const response = await fetch('/api/perception/status', { cache: 'no-store' });
    const payload = await response.json();
    if (payload.state) setState(payload.state);
    return payload;
  }, []);

  const refreshRecordings = useCallback(async () => {
    const response = await fetch('/api/recordings', { cache: 'no-store' });
    const payload = await response.json();
    if (payload.recordings) setRecordings(payload.recordings);
    return payload;
  }, []);

  useEffect(() => {
    let closed = false;
    refreshStatus().catch(() => setConnection('offline'));
    refreshPerception().catch(() => {});
    refreshRecordings().catch(() => {});
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const port = window.location.port === '5173' ? '8787' : window.location.port;
    const ws = new WebSocket(`${protocol}//${window.location.hostname}:${port}/api/telemetry`);
    ws.onopen = () => setConnection('connected');
    ws.onclose = () => {
      if (!closed) setConnection('offline');
    };
    ws.onerror = () => setConnection('offline');
    ws.onmessage = (event) => {
      const message = JSON.parse(event.data);
      if (message.type === 'snapshot') setState(message.data);
      if (message.type === 'telemetry') setState((previous) => mergeTelemetryPatch(previous, message.data));
      if (message.type === 'runtime-patch') setState((previous) => mergeRuntimePatch(previous, message.data));
      if (message.type === 'log') setState((previous) => appendLog(previous, message.data));
    };
    const poll = setInterval(() => {
      refreshStatus().catch(() => setConnection('offline'));
      refreshRecordings().catch(() => {});
    }, 6000);
    return () => {
      closed = true;
      clearInterval(poll);
      ws.close();
    };
  }, [refreshPerception, refreshRecordings, refreshStatus]);

  useEffect(() => {
    if (connection !== 'connected') return undefined;
    const sendHeartbeat = () => {
      fetch('/api/heartbeat', { method: 'POST' }).catch(() => setConnection('offline'));
    };
    sendHeartbeat();
    const interval = setInterval(sendHeartbeat, HEARTBEAT_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [connection]);

  useEffect(() => {
    const stop = () => {
      navigator.sendBeacon(
        '/api/drive',
        new Blob([JSON.stringify({ forward: 0, turn: 0, strafe: 0 })], { type: 'application/json' })
      );
    };
    const unloadStop = () => {
      if (config.control.heartbeatProtectionEnabled === false) {
        stop();
        return;
      }
      navigator.sendBeacon('/api/emergency-stop', new Blob(['{}'], { type: 'application/json' }));
    };
    window.addEventListener('blur', stop);
    window.addEventListener('beforeunload', unloadStop);
    return () => {
      window.removeEventListener('blur', stop);
      window.removeEventListener('beforeunload', unloadStop);
    };
  }, [config.control.heartbeatProtectionEnabled]);

  const postAction = useCallback(async (path, label) => {
    setBusy(label);
    try {
      const response = await fetch(path, { method: 'POST' });
      const payload = await response.json();
      if (payload.state) setState(payload.state);
      await refreshStatus();
      return payload;
    } finally {
      setBusy(null);
    }
  }, [refreshStatus]);

  const postJsonAction = useCallback(async (path, body, label) => {
    setBusy(label);
    try {
      const response = await fetch(path, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(body ?? {})
      });
      const payload = await response.json();
      if (payload.state) setState(payload.state);
      await refreshRecordings().catch(() => {});
      return payload;
    } finally {
      setBusy(null);
    }
  }, [refreshRecordings]);

  const sendDrive = useCallback((input, immediate = false) => {
    const now = performance.now();
    const next = {
      ...input,
      linearLimit,
      angularLimit
    };
    sendDriveRef.current.pending = next;
    const delay = immediate ? 0 : Math.max(0, DRIVE_PUBLISH_INTERVAL_MS - (now - sendDriveRef.current.lastSent));
    if (sendDriveRef.current.timer) return;
    sendDriveRef.current.timer = setTimeout(async () => {
      const payload = sendDriveRef.current.pending;
      sendDriveRef.current.timer = null;
      sendDriveRef.current.lastSent = performance.now();
      try {
        const response = await fetch('/api/drive', {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify(payload)
        });
        const body = await response.json();
        if (body.state) setState(body.state);
      } catch {
        setConnection('offline');
      }
    }, delay);
  }, [angularLimit, linearLimit]);

  const stopDrive = useCallback(() => {
    targetDriveRef.current = { forward: 0, turn: 0, strafe: 0 };
    smoothedDriveRef.current = { forward: 0, turn: 0, strafe: 0 };
    setDriveVector({ forward: 0, turn: 0, strafe: 0 });
    setKeyboardActive(false);
    sendDrive({ forward: 0, turn: 0, strafe: 0 }, true);
  }, [sendDrive]);

  const applyJoystickSmoothing = useCallback((immediate = false) => {
    const next = smoothJoystickVector(smoothedDriveRef.current, targetDriveRef.current);
    smoothedDriveRef.current = next;
    setDriveVector(next);
    sendDrive(next, immediate);
  }, [sendDrive]);

  const handleJoystickVector = useCallback((vector) => {
    pressedKeysRef.current.clear();
    setKeyboardActive(false);
    targetDriveRef.current = vector;
    applyJoystickSmoothing(true);
  }, [applyJoystickSmoothing]);

  const sendKeyboardVector = useCallback((immediate = false) => {
    const vector = keyboardVectorFromCodes(pressedKeysRef.current);
    const hasMotion = vector.forward !== 0 || vector.turn !== 0 || vector.strafe !== 0;
    if (!canDrive) {
      setKeyboardActive(false);
      setDriveVector({ forward: 0, turn: 0, strafe: 0 });
      return;
    }
    setKeyboardActive(hasMotion);
    targetDriveRef.current = vector;
    smoothedDriveRef.current = vector;
    setDriveVector(vector);
    if (!hasMotion) {
      sendDrive({ forward: 0, turn: 0, strafe: 0 }, true);
      return;
    }
    sendDrive(vector, immediate);
  }, [canDrive, sendDrive]);

  useEffect(() => {
    if (!keyboardActive || !canDrive || configOpen) return undefined;
    const interval = setInterval(() => sendKeyboardVector(), DRIVE_PUBLISH_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [canDrive, configOpen, keyboardActive, sendKeyboardVector]);

  useEffect(() => {
    if (!canDrive || configOpen || keyboardActive) return undefined;
    const interval = setInterval(() => {
      if (!hasMotion(targetDriveRef.current) && !hasMotion(smoothedDriveRef.current)) return;
      applyJoystickSmoothing();
    }, DRIVE_PUBLISH_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [applyJoystickSmoothing, canDrive, configOpen, keyboardActive]);

  useEffect(() => {
    function isEditableTarget(target) {
      return target?.closest?.('input, textarea, select, [contenteditable="true"]');
    }
    function resetKeys() {
      if (pressedKeysRef.current.size > 0) {
        pressedKeysRef.current.clear();
        stopDrive();
      }
    }
    async function handleKeyDown(event) {
      if (isEditableTarget(event.target) || configOpen) return;
      if (event.code === 'Space') {
        event.preventDefault();
        if (!event.repeat) {
          pressedKeysRef.current.clear();
          stopDrive();
          await postAction('/api/emergency-stop', 'stop');
        }
        return;
      }
      if (!isDriveKeyCode(event.code)) return;
      event.preventDefault();
      const before = pressedKeysRef.current.size;
      pressedKeysRef.current.add(event.code);
      if (pressedKeysRef.current.size !== before || event.repeat) {
        sendKeyboardVector(true);
      }
    }
    function handleKeyUp(event) {
      if (!isDriveKeyCode(event.code)) return;
      event.preventDefault();
      pressedKeysRef.current.delete(event.code);
      sendKeyboardVector(true);
    }

    window.addEventListener('keydown', handleKeyDown);
    window.addEventListener('keyup', handleKeyUp);
    window.addEventListener('blur', resetKeys);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
      window.removeEventListener('keyup', handleKeyUp);
      window.removeEventListener('blur', resetKeys);
    };
  }, [configOpen, postAction, sendKeyboardVector, stopDrive]);

  const voltageFresh = connection === 'connected' && isTelemetryFresh(telemetry.voltage);
  const topMetrics = useMemo(() => ([
    { label: 'Safety', value: navigation.safetyState, tone: navigation.safetyState === 'READY' ? 'green' : 'red' },
    { label: 'Source', value: navigation.activeSource, tone: navigation.activeSource === 'BLOCKED' ? 'red' : 'teal' },
    { label: '小车 IP', value: config.car.host, tone: 'teal' },
    { label: 'SSH', value: status.ssh.connected ? '已连接' : '离线', tone: status.ssh.connected ? 'green' : 'red' },
    { label: 'Docker', value: status.services.docker ? '运行中' : '已停止', tone: status.services.docker ? 'green' : 'amber' },
    { label: 'ROSBridge', value: state.runtime.rosbridge.connected ? '已连接' : '未连接', tone: state.runtime.rosbridge.connected ? 'green' : 'red' },
    { label: '摄像头', value: status.ports.video6500 ? '视频就绪' : '无视频流', tone: status.ports.video6500 ? 'green' : 'amber' },
    { label: '报警', value: `${alarms.summary?.active ?? 0} 活跃`, tone: (alarms.summary?.critical ?? 0) > 0 ? 'red' : (alarms.summary?.warning ?? 0) > 0 ? 'amber' : 'green' },
    { label: '主车电量', value: formatBatterySummary(telemetry.voltage, voltageFresh), tone: voltageFresh ? 'green' : 'muted' }
  ]), [alarms.summary, config.car.host, navigation, state.runtime.rosbridge.connected, status, telemetry.voltage, voltageFresh]);

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <Icon name="car" />
          <span>智能小车控制台</span>
        </div>
        <div className="top-metrics">
          {topMetrics.map((metric) => (
            <StatusMetric key={metric.label} {...metric} />
          ))}
        </div>
        <div className="top-actions">
          <button className="icon-button danger" onClick={() => postAction('/api/emergency-stop', 'stop')} title="急停">
            <Icon name="stop" />
          </button>
          <button className="icon-button" onClick={() => setConfigOpen(true)} title="连接设置">
            <Icon name="settings" />
          </button>
        </div>
      </header>

      <main className="workbench">
        <NavigationRail activeSection={activeSection} onSelect={setActiveSection} alarmCount={alarms.summary?.active ?? 0} />
        <ServicePanel status={status} rosbridge={state.runtime.rosbridge} telemetry={telemetry} navigation={navigation} />
        <section className="center-zone">
          {activeSection === 'overview' && (
            <>
              <div className="visual-grid overview-visual-grid">
                <CameraPanel host={config.car.host} videoReady={status.ports.video6500} detections={telemetry.detections} video={video} />
                <LidarPanel lidar={telemetry.lidar} />
                <Joystick
                  compact
                  title="实时遥控"
                  disabled={!canDrive}
                  driveReady={driveReady}
                  emergencyStopActive={safety.emergencyStopActive}
                  blockers={status.blockers}
                  busy={busy}
                  vector={driveVector}
                  keyboardActive={keyboardActive}
                  onVector={handleJoystickVector}
                  onStop={stopDrive}
                  onResume={() => postAction('/api/safety/reset', 'resume')}
                />
              </div>
              <OverviewGrid
                telemetry={telemetry}
                status={status}
                alarms={alarms}
                command={state.runtime.command}
                video={video}
                canDrive={canDrive}
                emergencyStopActive={safety.emergencyStopActive}
              />
            </>
          )}
          {activeSection === 'map' && (
            <MapMonitor
              telemetry={telemetry}
              navigation={navigation}
              capabilities={capabilities}
              topicActivity={state.runtime.topicActivity ?? {}}
            />
          )}
          {activeSection === 'capabilities' && (
            <CapabilityCenter capabilities={capabilities} topicActivity={state.runtime.topicActivity ?? {}} />
          )}
          {activeSection === 'vision' && (
            <>
              <VideoConfigPanel
                host={config.car.host}
                video={video}
                videoReady={status.ports.video6500}
                detections={telemetry.detections}
                onSave={(nextVideo) => postJsonAction('/api/video/config', { video: nextVideo }, 'video-config')}
              />
              <PerceptionWorkbench
                telemetry={telemetry}
                perception={perception}
                recording={recording}
                recordings={recordings}
                busy={busy}
                onStartPerception={() => postAction('/api/perception/start', 'perception-start')}
                onStopPerception={() => postAction('/api/perception/stop', 'perception-stop')}
                onRefreshPerception={refreshPerception}
                onStartRecording={(topics) => postJsonAction('/api/recordings/start', { topics }, 'recording-start')}
                onStopRecording={() => postAction('/api/recordings/stop', 'recording-stop')}
                onDeleteRecording={async (id) => {
                  await fetch(`/api/recordings/${encodeURIComponent(id)}`, { method: 'DELETE' });
                  await refreshRecordings();
                }}
              />
            </>
          )}
          {activeSection === 'remote' && (
            <div className="control-grid expanded">
              <Joystick
                disabled={!canDrive}
                driveReady={driveReady}
                emergencyStopActive={safety.emergencyStopActive}
                blockers={status.blockers}
                busy={busy}
                vector={driveVector}
                keyboardActive={keyboardActive}
                onVector={handleJoystickVector}
                onStop={stopDrive}
                onResume={() => postAction('/api/safety/reset', 'resume')}
              />
              <SpeedPanel
                linearLimit={linearLimit}
                angularLimit={angularLimit}
                maxLinear={config.control.maxLinearMps}
                maxAngular={config.control.maxAngularRps}
                setLinearLimit={setLinearLimit}
                setAngularLimit={setAngularLimit}
                onEmergency={() => postAction('/api/emergency-stop', 'stop')}
                disabled={!canDrive}
              />
              <ServiceActions
                busy={busy}
                onStart={() => postAction('/api/services/start', 'start')}
                onStop={() => postAction('/api/services/stop', 'stop')}
                onRefresh={refreshStatus}
              />
              <NavigationActions
                navigation={navigation}
                profile={config.navigation}
                busy={busy}
                onStart={() => postAction('/api/patrol/start', 'patrol-start')}
                onCancel={() => postAction('/api/patrol/cancel', 'patrol-cancel')}
                onReturnHome={() => postAction('/api/patrol/return-home', 'return-home')}
                onSimulateLowBattery={() => postAction('/api/safety/simulate-low-battery', 'simulate-low-battery')}
                onResetSafety={() => postAction('/api/safety/reset', 'resume')}
              />
              <RemoteSafetyPanel command={state.runtime.command} canDrive={canDrive} blockers={status.blockers} />
            </div>
          )}
          {activeSection === 'alarms' && (
            <AlarmPanel
              alarms={alarms}
              onAck={(id) => postAction(`/api/alarms/${encodeURIComponent(id)}/ack`, 'alarm-ack')}
              onResolve={(id) => postAction(`/api/alarms/${encodeURIComponent(id)}/resolve`, 'alarm-resolve')}
            />
          )}
          {activeSection === 'logs' && <LogConsole logs={logs} />}
        </section>
        <SensorInspector
          telemetry={telemetry}
          status={status}
          command={state.runtime.command}
          blockers={status.blockers}
          telemetryOnline={connection === 'connected'}
        />
      </main>

      {configOpen && (
        <ConfigDialog
          config={config}
          onClose={() => setConfigOpen(false)}
          onSaved={(next) => setConfig(next)}
        />
      )}
    </div>
  );
}

function StatusMetric({ label, value, tone }) {
  return (
    <div className="status-metric">
      <span>{label}</span>
      <strong className={`tone-${tone}`}>
        <i />
        {value ?? '未连接'}
      </strong>
    </div>
  );
}

function NavigationRail({ activeSection, onSelect, alarmCount = 0 }) {
  const items = [
    ['overview', 'home', '总览'],
    ['map', 'map', '地图与导航'],
    ['vision', 'camera', '视觉'],
    ['capabilities', 'chip', '能力中心'],
    ['remote', 'scope', '遥控'],
    ['alarms', 'clipboard', `报警${alarmCount > 0 ? ` ${alarmCount}` : ''}`],
    ['logs', 'terminal', '日志']
  ];
  return (
    <nav className="nav-rail" aria-label="控制台分区">
      {items.map(([key, icon, label]) => (
        <button className={activeSection === key ? 'active' : ''} key={key} title={label} onClick={() => onSelect(key)}>
          <Icon name={icon} />
        </button>
      ))}
    </nav>
  );
}

function CapabilityCenter({ capabilities, topicActivity }) {
  const groups = capabilities?.groups ?? [];
  const visibleItems = visibleCapabilityItems(capabilities);
  return (
    <section className="panel capability-center">
      <PanelTitle
        title="X3 真实能力中心"
        right={(
          <span className={`mode-pill ${capabilities?.stale ? 'warn' : ''}`}>
            {capabilities?.stale ? '证据过期 / 未运行' : '新鲜只读证据'}
          </span>
        )}
      />
      <div className="capability-summary">
        <span>目标设备：X3 麦克纳姆底盘</span>
        <span>探测：{formatDateTime(capabilities?.detectedAt)}</span>
        <span>{capabilities?.error ?? '未启动任何容器、节点或服务'}</span>
      </div>
      <div className="capability-groups">
        {groups.length === 0 && <div className="capability-empty">等待首次只读能力探测；不会自动启动 ROS 容器或节点。</div>}
        {groups.map((group) => {
          const items = visibleItems.filter((item) => item.group === group.key);
          if (items.length === 0) return null;
          return (
            <section className="capability-group" key={group.key}>
              <h3>{group.label}</h3>
              <div className="capability-grid">
                {items.map((item) => <CapabilityCard key={item.key} item={item} topicActivity={topicActivity} />)}
              </div>
            </section>
          );
        })}
      </div>
    </section>
  );
}

function CapabilityCard({ item, topicActivity }) {
  const ui = capabilityUiState(item);
  const topics = (item.evidence?.topics ?? []).map((entry) => {
    const topic = typeof entry === 'string' ? entry : entry.topic;
    const live = topicActivity?.[topic];
    if (live) return `${topic} · ${formatTopicActivity(live)}`;
    if (typeof entry === 'string') return entry;
    return `${topic}${entry.frequencyHz == null ? '' : ` · ${entry.frequencyHz}Hz`}${entry.ageMs == null ? '' : ` · ${entry.ageMs}ms`}`;
  });
  return (
    <article className={`capability-card runtime-${String(item.runtime).toLowerCase()} safety-${String(item.safety).toLowerCase()}`}>
      <header>
        <strong>{item.label}</strong>
        <span>{ui.availability} · {ui.runtime}</span>
      </header>
      <p>{item.blockedReason ?? item.reason ?? capabilityAdvice(item)}</p>
      <div className="capability-badges">
        <span>{item.safety}</span>
        {item.lastConfirmedAt && <span>确认于 {formatDateTime(item.lastConfirmedAt)}</span>}
      </div>
      <details>
        <summary>ROS / 硬件证据</summary>
        <EvidenceRow label="硬件" values={item.evidence?.hardware} />
        <EvidenceRow label="ROS 包" values={item.evidence?.packages} />
        <EvidenceRow label="可执行文件" values={item.evidence?.executables} />
        <EvidenceRow label="节点" values={item.evidence?.nodes} />
        <EvidenceRow label="Topic" values={topics} />
        <EvidenceRow label="期望 Topic" values={item.requirements?.topics} />
      </details>
    </article>
  );
}

function EvidenceRow({ label, values }) {
  const entries = Array.isArray(values) ? values : [];
  return <div className="evidence-row"><span>{label}</span><code>{entries.length ? entries.join(', ') : '未发现当前运行证据'}</code></div>;
}

function capabilityAdvice(item) {
  if (item.runtime === 'ACTIVE') return '能力当前有真实节点或 topic 证据。';
  if (item.runtime === 'STALE') return '检查 SSH 与 ROS 容器状态；不会自动启动任何服务。';
  if (item.availability === 'UNKNOWN') return '等待一次成功的只读硬件与 ROS 探测。';
  return '能力已具备；如需运行，请按既有安全流程在车端启动。';
}

function ServicePanel({ status, rosbridge, telemetry, navigation }) {
  const modules = [
    { label: 'Safety state', ok: navigation.safetyState === 'READY', detail: navigation.safetyState },
    { label: 'Command source', ok: !['UNKNOWN', 'BLOCKED'].includes(navigation.activeSource), detail: navigation.activeSource },
    { label: 'Patrol', ok: !['INVALID', 'UNKNOWN'].includes(navigation.patrol.state), detail: `${navigation.patrol.mode ?? '-'} / ${navigation.patrol.state}` },
    { label: '底盘串口', ok: status.devices.chassisSerial, detail: status.devices.chassisPath ?? '串口缺失' },
    { label: '运动驱动', ok: status.services.chassis, detail: 'Mcnamu_driver_X3' },
    { label: '雷达扫描', ok: telemetry.lidar.connected || (status.devices.lidar && status.services.lidar), detail: '/scan' },
    { label: '摄像头视频', ok: status.ports.video6500, detail: '6500 MJPEG' },
    { label: 'IMU', ok: telemetry.imu.connected, detail: '/imu/data_raw' },
    { label: '电池电压', ok: telemetry.voltage.connected, detail: '/voltage' },
    { label: 'ROSBridge', ok: rosbridge.connected || status.ports.rosbridge9090, detail: '9090' },
    { label: '视频代理', ok: status.ports.video6500, detail: '6500' }
  ];
  const serviceRows = [
    ['底盘驱动', status.services.chassis],
    ['雷达驱动', status.services.lidar],
    ['相机节点', status.services.camera],
    ['ROSBridge', rosbridge.connected],
    ['视频流', status.ports.video6500],
    ['TCP 控制 6000', status.ports.control6000]
  ];

  return (
    <aside className="services-panel panel">
      <h2>服务</h2>
      <div className="service-switches">
        {serviceRows.map(([label, ok]) => (
          <div className="service-row" key={label}>
            <span className={`dot ${ok ? 'ok' : 'idle'}`} />
            <span>{label}</span>
            <strong className={`service-state-label ${ok ? 'ok-text' : 'warn-text'}`}>{ok ? '运行' : '停止'}</strong>
          </div>
        ))}
      </div>
      <div className="panel-rule" />
      <h2>模块状态</h2>
      <div className="module-list">
        {modules.map((item) => (
          <div className="module-row" key={item.label}>
            <Icon name="chip" />
            <span>{item.label}</span>
            <small>{item.detail}</small>
            <strong className={item.ok ? 'ok-text' : 'warn-text'}>{item.ok ? '正常' : '缺失'}</strong>
          </div>
        ))}
      </div>
    </aside>
  );
}

function CameraPanel({ host, videoReady, detections, video }) {
  const [imageOk, setImageOk] = useState(true);
  const [streamToken, setStreamToken] = useState(() => Date.now());
  const boxes = detections?.detections ?? [];
  useEffect(() => {
    setImageOk(true);
    setStreamToken(Date.now());
  }, [host, videoReady]);
  useEffect(() => {
    if (!videoReady || imageOk) return undefined;
    const timer = window.setInterval(() => {
      setImageOk(true);
      setStreamToken(Date.now());
    }, 3000);
    return () => window.clearInterval(timer);
  }, [imageOk, videoReady]);
  return (
    <section className="panel media-panel">
      <PanelTitle title="摄像头" right={<ToolbarIcons names={['camera', 'fullscreen', 'more']} />} />
      <div className="camera-frame">
        {videoReady && imageOk ? (
          <>
            <img
              src={`/api/video?host=${encodeURIComponent(host)}&v=${streamToken}`}
              alt="智能小车摄像头视频流"
              onLoad={() => setImageOk(true)}
              onError={() => setImageOk(false)}
            />
            <DetectionOverlay detections={detections} />
          </>
        ) : (
          <div className="camera-placeholder">
            <Icon name="camera" />
            <strong>视频流未连接</strong>
            <span>启动服务后代理 http://{host}:6500/video_feed</span>
          </div>
        )}
      </div>
      <div className="media-footer">
        <span>{imageOk && videoReady ? `MJPEG ${video?.width ?? 640}x${video?.height ?? 480}@${video?.fps ?? 20}` : '等待视频流'}</span>
        <span>{boxes.length > 0 ? `${boxes.length} 个检测框` : `${host}:6500`}</span>
      </div>
    </section>
  );
}

function DetectionOverlay({ detections }) {
  const boxes = detections?.detections ?? [];
  const sourceWidth = detections?.sourceWidth || 640;
  const sourceHeight = detections?.sourceHeight || 480;
  if (!detections?.topic) return null;
  if (!detections?.connected || boxes.length === 0) {
    return <div className="detection-empty">等待检测结果</div>;
  }
  return (
    <div className="detection-overlay">
      {boxes.map((box) => (
        <div
          key={box.id}
          className="detection-box"
          style={{
            left: `${(box.x / sourceWidth) * 100}%`,
            top: `${(box.y / sourceHeight) * 100}%`,
            width: `${(box.width / sourceWidth) * 100}%`,
            height: `${(box.height / sourceHeight) * 100}%`
          }}
        >
          <span>{box.label} {Math.round((box.confidence ?? 0) * 100)}%</span>
        </div>
      ))}
    </div>
  );
}

function LidarPanel({ lidar }) {
  const canvasRef = useRef(null);
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.floor(width * dpr);
    canvas.height = Math.floor(height * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    drawLidar(ctx, width, height, lidar);
  }, [lidar]);

  return (
    <section className={`panel lidar-panel ${lidar?.stale ? 'stale-visual' : ''}`}>
      <PanelTitle title="雷达" right={<div className="mode-pill">2D</div>} />
      <div className="lidar-canvas-wrap">
        <canvas ref={canvasRef} />
      </div>
      <div className="media-footer">
        <span>{lidar.connected ? `${lidar.points.length} 个真实扫描点` : '尚未收到 /scan'}</span>
        <span>{formatSampleAge(lidar)}</span>
      </div>
    </section>
  );
}

function OverviewGrid({ telemetry, status, alarms, command, video, canDrive, emergencyStopActive }) {
  const driveLabel = canDrive ? '允许' : emergencyStopActive ? '急停锁定' : status.canDrive ? '等待恢复' : '锁定';
  const heartbeatProtectionEnabled = command.heartbeat?.protectionEnabled !== false;
  const heartbeatLabel = heartbeatProtectionEnabled
    ? command.heartbeat?.connected ? `${command.heartbeat.ageMs ?? 0} ms` : '等待心跳'
    : '保护关闭';
  return (
    <section className="panel overview-panel">
      <PanelTitle title="运行总览" right={<span className="small-help">控制台优先</span>} />
      <div className="overview-grid">
        <DataGrid rows={[
          ['地图', telemetry.map?.connected ? `${telemetry.map.width}x${telemetry.map.height}` : '降级到 /scan'],
          ['机器人位姿', telemetry.pose?.connected ? `${fmt(telemetry.pose.pose?.x, ' m')}, ${fmt(telemetry.pose.pose?.y, ' m')} (${telemetry.pose.source})` : '等待 AMCL / TF'],
          ['当前算法输出', telemetry.detections?.connected ? `${telemetry.detections.count} 个目标` : '未发现真实检测 topic'],
          ['视频配置', `${video.width}x${video.height}@${video.fps} Q${video.jpegQuality}`],
          ['心跳', heartbeatLabel],
          ['可遥控', driveLabel]
        ]} />
        <div className="alarm-summary-strip">
          <strong>{alarms.summary?.active ?? 0}</strong>
          <span>活跃报警</span>
          <strong>{alarms.summary?.critical ?? 0}</strong>
          <span>严重</span>
          <strong>{alarms.summary?.warning ?? 0}</strong>
          <span>警告</span>
        </div>
      </div>
    </section>
  );
}

function MapMonitor({ telemetry, navigation, capabilities, topicActivity }) {
  const [layers, setLayers] = useState({
    map: true,
    globalCostmap: true,
    localCostmap: true,
    globalPath: true,
    localPath: true,
    patrolRoute: true,
    pose: true
  });
  const map = telemetry.map;
  const pose = telemetry.pose;
  const hasMap = map?.connected && map.mode === 'map' && map.cells?.length > 0
    && String(map.frameId ?? '').replace(/^\/+/, '') === 'map';
  const hasPose = Number.isFinite(pose?.pose?.x) && Number.isFinite(pose?.pose?.y)
    && String(pose?.frameId ?? '').replace(/^\/+/, '') === 'map';
  const toggle = (key) => setLayers((current) => ({ ...current, [key]: !current[key] }));
  return (
    <section className="panel map-monitor">
      <PanelTitle
        title="地图与导航（只读）"
        right={<span className={`mode-pill ${hasMap ? '' : 'warn'}`}>{hasMap ? '/map OccupancyGrid' : '/scan 局部视图'}</span>}
      />
      <div className="map-layer-toolbar" aria-label="地图图层">
        {[
          ['map', '地图'], ['globalCostmap', '全局 costmap'], ['localCostmap', '局部 costmap'],
          ['globalPath', '全局路径'], ['localPath', '局部路径'], ['patrolRoute', '巡航路线'], ['pose', '当前位置']
        ].map(([key, label]) => (
          <label key={key}><input type="checkbox" checked={layers[key]} onChange={() => toggle(key)} />{label}</label>
        ))}
      </div>
      <div className="map-layout">
        <div>
          <MapCanvas telemetry={telemetry} layers={layers} />
          <div className="map-legend">
            <span className="legend-map">栅格</span><span className="legend-global">全局代价/路径</span>
            <span className="legend-local">局部代价/路径</span><span className="legend-route">巡航路线/航点</span>
          </div>
        </div>
        <div className="map-side">
          <DataGrid rows={[
            ['模式', hasMap ? '全局栅格地图' : '局部雷达占据视图'],
            ['地图尺寸', hasMap ? `${map.width} x ${map.height}` : '无 /map'],
            ['分辨率', hasMap ? fmt(map.resolution, ' m/cell') : '按雷达量程缩放'],
            ['全局位姿来源', hasPose ? `${pose.source ?? '最后可信值'}${pose.stale || !pose.connected ? '（过期）' : ''}` : '等待 AMCL / TF'],
            ['机器人 X', hasPose ? fmt(pose.pose?.x, ' m') : '不可用'],
            ['机器人 Y', hasPose ? fmt(pose.pose?.y, ' m') : '不可用'],
            ['机器人朝向', hasPose ? fmt((pose.pose?.yaw ?? 0) * 180 / Math.PI, '°') : '不可用'],
            ['Cartographer', capabilityStatus(capabilities, 'mapping')],
            ['AMCL / Nav2', capabilityStatus(capabilities, 'localization_navigation')],
            ['NavigateToPose', `${navigation?.action?.status ?? 'UNKNOWN'} / ${navigation?.action?.activeGoals ?? 0} active`],
            ['巡航', `${navigation?.patrol?.state ?? 'UNKNOWN'} / 航点 ${navigation?.patrol?.waypoint ?? '-'}`],
            ['重试次数', navigation?.patrol?.attempt ?? 0],
            ['巡航路线', telemetry.patrolRoute?.empty ? '未配置（空 Path）' : `${telemetry.patrolRoute?.totalPoints ?? 0} 个点`],
            ['/map 频率', formatTopicActivity(topicActivity?.['/map'])],
            ['/amcl_pose 频率', formatTopicActivity(topicActivity?.['/amcl_pose'])]
          ]} />
          <p className="muted-note">
            {hasMap
              ? '当前位置优先采用新鲜 /amcl_pose，否则组合 map→odom→base_footprint；画布不接受点击目标。'
              : '当前未收到 /map，仅显示最后一次真实 /scan；不会生成模拟雷达点，也不会把 /odom 当作全局坐标。'}
          </p>
        </div>
      </div>
    </section>
  );
}

function MapCanvas({ telemetry, layers }) {
  const canvasRef = useRef(null);
  const { map, pose, lidar, globalCostmap, localCostmap, globalPath, localPath, patrolRoute } = telemetry;
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.floor(width * dpr);
    canvas.height = Math.floor(height * dpr);
    const ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    drawMapMonitor(ctx, width, height, {
      map, pose, lidar, globalCostmap, localCostmap, globalPath, localPath, patrolRoute
    }, layers);
  }, [layers, map, pose, lidar, globalCostmap, localCostmap, globalPath, localPath, patrolRoute]);
  const stale = telemetry.map?.stale && telemetry.lidar?.stale;
  return <canvas ref={canvasRef} className={`map-canvas ${stale ? 'stale-visual' : ''}`} aria-label="只读地图，不能发送导航目标" />;
}

function drawMapMonitor(ctx, width, height, telemetry, layers) {
  const { map, pose, lidar, globalCostmap, localCostmap, globalPath, localPath, patrolRoute } = telemetry;
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = '#081016';
  ctx.fillRect(0, 0, width, height);
  if (map?.connected && map.mode === 'map' && map.cells?.length
      && String(map.frameId ?? '').replace(/^\/+/, '') === 'map') {
    const projection = drawOccupancyGrid(ctx, width, height, map, layers.map);
    if (layers.globalCostmap) drawCostmapOverlay(ctx, map, globalCostmap, projection, '#e2a31b');
    if (layers.localCostmap) drawCostmapOverlay(ctx, map, localCostmap, projection, '#e8505b');
    if (layers.globalPath) drawMapPath(ctx, map, globalPath, projection, '#68a9ff', 2);
    if (layers.localPath) drawMapPath(ctx, map, localPath, projection, '#f7d154', 2);
    if (layers.patrolRoute) drawMapPath(ctx, map, patrolRoute, projection, '#d76cff', 3, true);
    if (layers.pose && Number.isFinite(pose?.pose?.x) && Number.isFinite(pose?.pose?.y)
        && String(pose?.frameId ?? '').replace(/^\/+/, '') === 'map') {
      drawMapPose(ctx, map, pose, projection);
    }
    return;
  }
  drawLocalScanMap(ctx, width, height, lidar);
}

function drawOccupancyGrid(ctx, width, height, map, visible = true) {
  const gridW = map.previewWidth ?? map.width;
  const gridH = map.previewHeight ?? map.height;
  const cell = Math.min(width / gridW, height / gridH) * 0.94;
  const offsetX = (width - gridW * cell) / 2;
  const offsetY = (height - gridH * cell) / 2;
  if (visible) {
    for (let y = 0; y < gridH; y += 1) {
      for (let x = 0; x < gridW; x += 1) {
        const value = map.cells[y * gridW + x] ?? -1;
        ctx.fillStyle = value < 0 ? '#1b2630' : value >= 65 ? '#d8e1e8' : value > 20 ? '#5d6c75' : '#0d151b';
        ctx.fillRect(offsetX + x * cell, offsetY + (gridH - 1 - y) * cell, Math.ceil(cell), Math.ceil(cell));
      }
    }
  }
  ctx.strokeStyle = '#2f4854';
  ctx.strokeRect(offsetX, offsetY, gridW * cell, gridH * cell);
  return { gridW, gridH, cell, offsetX, offsetY };
}

function drawCostmapOverlay(ctx, map, costmap, projection, color) {
  if (!costmap?.connected || !costmap.cells?.length || !costmap.resolution
      || String(costmap.frameId ?? '').replace(/^\/+/, '') !== 'map') return;
  const width = costmap.previewWidth ?? costmap.width;
  const height = costmap.previewHeight ?? costmap.height;
  ctx.save();
  ctx.globalAlpha = costmap.stale ? 0.18 : 0.38;
  ctx.fillStyle = color;
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      if ((costmap.cells[y * width + x] ?? -1) < 50) continue;
      const cellSize = costmap.resolution * (costmap.step || 1);
      const corners = [[x, y], [x + 1, y], [x + 1, y + 1], [x, y + 1]].map(([cellX, cellY]) => {
        const localX = cellX * cellSize;
        const localY = cellY * cellSize;
        const yaw = costmap.origin.yaw ?? 0;
        const worldX = costmap.origin.x + Math.cos(yaw) * localX - Math.sin(yaw) * localY;
        const worldY = costmap.origin.y + Math.sin(yaw) * localX + Math.cos(yaw) * localY;
        return mapPointToCanvas(map, worldX, worldY, projection);
      });
      ctx.beginPath();
      corners.forEach((point, index) => index === 0 ? ctx.moveTo(point.x, point.y) : ctx.lineTo(point.x, point.y));
      ctx.closePath();
      ctx.fill();
    }
  }
  ctx.restore();
}

function drawMapPath(ctx, map, path, projection, color, lineWidth, waypoints = false) {
  if (!path?.connected || !path.points?.length || String(path.frameId ?? '').replace(/^\/+/, '') !== 'map') return;
  ctx.save();
  ctx.strokeStyle = color;
  ctx.fillStyle = color;
  ctx.lineWidth = lineWidth;
  ctx.globalAlpha = path.stale ? 0.35 : 0.95;
  ctx.beginPath();
  path.points.forEach((point, index) => {
    const canvas = mapPointToCanvas(map, point.x, point.y, projection);
    if (index === 0) ctx.moveTo(canvas.x, canvas.y);
    else ctx.lineTo(canvas.x, canvas.y);
  });
  ctx.stroke();
  if (waypoints) {
    for (const point of path.points) {
      const canvas = mapPointToCanvas(map, point.x, point.y, projection);
      ctx.beginPath();
      ctx.arc(canvas.x, canvas.y, 4, 0, Math.PI * 2);
      ctx.fill();
    }
  }
  ctx.restore();
}

function drawMapPose(ctx, map, pose, projection) {
  const point = mapPointToCanvas(map, pose.pose.x, pose.pose.y, projection);
  ctx.save();
  ctx.globalAlpha = pose.stale || !pose.connected ? 0.35 : 1;
  drawRobotMarker(ctx, point.x, point.y, -((pose.pose.yaw ?? 0) - (map.origin.yaw ?? 0)), Math.max(10, projection.cell * 3));
  ctx.restore();
}

function mapPointToCanvas(map, x, y, projection) {
  const dx = x - map.origin.x;
  const dy = y - map.origin.y;
  const yaw = map.origin.yaw ?? 0;
  const scale = map.resolution * (map.step || 1);
  const mx = (Math.cos(yaw) * dx + Math.sin(yaw) * dy) / scale;
  const my = (-Math.sin(yaw) * dx + Math.cos(yaw) * dy) / scale;
  return {
    x: projection.offsetX + mx * projection.cell,
    y: projection.offsetY + (projection.gridH - 1 - my) * projection.cell
  };
}

function drawLocalScanMap(ctx, width, height, lidar) {
  const cx = width / 2;
  const cy = height * 0.58;
  const radius = Math.min(width, height) * 0.42;
  const maxRange = Math.max(2, lidar?.rangeMax || 12);
  ctx.strokeStyle = '#20313a';
  for (let ring = 1; ring <= 5; ring += 1) {
    ctx.beginPath();
    ctx.arc(cx, cy, radius * ring / 5, 0, Math.PI * 2);
    ctx.stroke();
  }
  for (const point of lidar?.points ?? []) {
    const normalized = Math.min(point.range / maxRange, 1);
    const x = cx + Math.cos(point.angle - Math.PI / 2) * radius * normalized;
    const y = cy + Math.sin(point.angle - Math.PI / 2) * radius * normalized;
    ctx.fillStyle = lidar?.stale ? '#48616c' : '#12c9b7';
    ctx.fillRect(x, y, 2, 2);
  }
  drawRobotMarker(ctx, cx, cy, 0, 18);
}

function drawRobotMarker(ctx, x, y, yaw, size) {
  ctx.save();
  ctx.translate(x, y);
  ctx.rotate(yaw);
  ctx.fillStyle = '#f0f6fa';
  ctx.beginPath();
  ctx.moveTo(size, 0);
  ctx.lineTo(-size * 0.65, size * 0.55);
  ctx.lineTo(-size * 0.35, 0);
  ctx.lineTo(-size * 0.65, -size * 0.55);
  ctx.closePath();
  ctx.fill();
  ctx.strokeStyle = '#12c9b7';
  ctx.stroke();
  ctx.restore();
}

function drawLidar(ctx, width, height, lidar) {
  ctx.clearRect(0, 0, width, height);
  const cx = width / 2;
  const cy = height / 2 + 8;
  const radius = Math.min(width, height) * 0.42;
  const maxRange = Math.max(2, lidar.rangeMax || 12);
  ctx.fillStyle = '#091014';
  ctx.fillRect(0, 0, width, height);

  ctx.strokeStyle = '#20313a';
  ctx.lineWidth = 1;
  for (let ring = 1; ring <= 4; ring += 1) {
    ctx.beginPath();
    ctx.arc(cx, cy, (radius / 4) * ring, 0, Math.PI * 2);
    ctx.stroke();
  }
  for (let line = 0; line < 8; line += 1) {
    const angle = (Math.PI * 2 / 8) * line;
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(cx + Math.cos(angle) * radius, cy + Math.sin(angle) * radius);
    ctx.stroke();
  }

  ctx.strokeStyle = '#0d7b68';
  ctx.beginPath();
  ctx.arc(cx, cy, radius * 0.34, 0, Math.PI * 2);
  ctx.stroke();

  const points = lidar?.points ?? [];
  for (const point of points) {
    const normalized = Math.min(point.range / maxRange, 1);
    const x = cx + Math.cos(point.angle - Math.PI / 2) * radius * normalized;
    const y = cy + Math.sin(point.angle - Math.PI / 2) * radius * normalized;
    const hue = 130 - Math.min(110, normalized * 110);
    ctx.fillStyle = lidar?.stale ? '#48616c' : `hsl(${hue} 92% 48%)`;
    ctx.fillRect(x, y, 2, 2);
  }

  ctx.fillStyle = '#dbe8f1';
  ctx.beginPath();
  ctx.roundRect(cx - 12, cy - 18, 24, 36, 8);
  ctx.fill();
  ctx.fillStyle = '#222a31';
  ctx.fillRect(cx - 8, cy - 10, 16, 20);
  ctx.strokeStyle = '#f0f6fa';
  ctx.strokeRect(cx - 12, cy - 18, 24, 36);

  ctx.fillStyle = '#8294a0';
  ctx.font = '12px ui-monospace, SFMono-Regular, Consolas, monospace';
  ctx.fillText('10m', 12, 28);
  ctx.fillText('0m', 16, cy - 6);
  if (!lidar?.connected) {
    ctx.fillStyle = '#61717b';
    ctx.fillText('no real scan', width - 92, height - 16);
  }
}

function PerceptionWorkbench({
  telemetry,
  perception,
  recording,
  recordings,
  busy,
  onStartPerception,
  onStopPerception,
  onRefreshPerception,
  onStartRecording,
  onStopRecording,
  onDeleteRecording
}) {
  const topicOptions = useMemo(() => recordingTopicOptions(perception), [perception]);
  const [selectedTopics, setSelectedTopics] = useState(DEFAULT_RECORD_TOPICS);

  useEffect(() => {
    const discovered = topicOptions.map((option) => option.topic);
    if (discovered.length === 0) return;
    setSelectedTopics((current) => [...new Set([...current.filter((topic) => DEFAULT_RECORD_TOPICS.includes(topic)), ...discovered])]);
  }, [topicOptions]);

  const toggleTopic = (topic) => {
    setSelectedTopics((current) => (
      current.includes(topic) ? current.filter((item) => item !== topic) : [...current, topic]
    ));
  };

  return (
    <section className="perception-workbench panel">
      <PanelTitle
        title="感知与记录"
        right={(
          <div className="perception-actions">
            <button disabled={Boolean(busy)} onClick={onRefreshPerception}><Icon name="refresh" />刷新</button>
            <button disabled={Boolean(busy)} onClick={onStartPerception}><Icon name="play" />启动感知</button>
            <button disabled={Boolean(busy)} onClick={onStopPerception}><Icon name="square" />停止感知</button>
          </div>
        )}
      />
      <div className="perception-grid">
        <RasterPreview title="RGB" sample={telemetry.camera} fallback="等待 RGB 图像 topic" />
        <RasterPreview title="深度" sample={telemetry.depth} fallback="等待 depth image" />
        <RasterPreview title="红外" sample={telemetry.ir} fallback="等待 IR image" />
        <PointCloudPreview pointCloud={telemetry.pointCloud} />
        <TrackingPreview tracking={telemetry.tracking} perception={perception} />
        <RecordingPanel
          recording={recording}
          recordings={recordings}
          topicOptions={topicOptions}
          selectedTopics={selectedTopics}
          onToggleTopic={toggleTopic}
          onStart={() => onStartRecording(selectedTopics)}
          onStop={onStopRecording}
          onDelete={onDeleteRecording}
          busy={busy}
        />
      </div>
    </section>
  );
}

function VideoConfigPanel({ host, video, videoReady, detections, onSave }) {
  const [draft, setDraft] = useState(video);
  useEffect(() => setDraft(video), [video]);
  const update = (key, value) => setDraft((current) => ({ ...current, [key]: Number(value) }));
  return (
    <div className="video-ai-layout">
      <CameraPanel host={host} videoReady={videoReady} detections={detections} video={video} />
      <section className="panel video-config-panel">
        <PanelTitle title="视频与真实算法输出" right={<span className="small-help">目标延迟 ≤ {video.latencyTargetMs ?? 100}ms 需实车测量</span>} />
        <div className="video-config">
          <DataGrid rows={[
            ['检测 Topic', detections?.topic ?? '等待发现'],
            ['当前算法', detectionAlgorithmName(detections?.topic)],
            ['检测协议', detections?.type ?? '未发现真实检测 topic'],
            ['检测目标', detections?.connected ? detections.count : '无真实检测输出'],
            ['视频代理', videoReady ? `${host}:6500/video_feed` : '未就绪']
          ]} />
          <div className="video-form">
            <label>宽度<input type="number" min="160" max="1920" value={draft.width ?? 640} onChange={(event) => update('width', event.target.value)} /></label>
            <label>高度<input type="number" min="120" max="1080" value={draft.height ?? 480} onChange={(event) => update('height', event.target.value)} /></label>
            <label>FPS<input type="number" min="1" max="60" value={draft.fps ?? 20} onChange={(event) => update('fps', event.target.value)} /></label>
            <label>JPEG<input type="number" min="20" max="95" value={draft.jpegQuality ?? 70} onChange={(event) => update('jpegQuality', event.target.value)} /></label>
            <button onClick={() => onSave(draft)}><Icon name="save" />保存视频配置</button>
          </div>
        </div>
      </section>
    </div>
  );
}

function RemoteSafetyPanel({ command, canDrive, blockers }) {
  const heartbeat = command?.heartbeat ?? {};
  const heartbeatProtectionEnabled = heartbeat.protectionEnabled !== false;
  const heartbeatStatus = heartbeatProtectionEnabled ? (heartbeat.connected ? '心跳在线' : '心跳等待') : '保护已关闭';
  const heartbeatStatusClass = heartbeatProtectionEnabled ? (heartbeat.connected ? 'ok-text' : 'bad-text') : 'warn-text';
  return (
    <section className="panel remote-safety-panel">
      <PanelTitle title="心跳与保护" right={<span className={heartbeatStatusClass}>{heartbeatStatus}</span>} />
      <DataGrid rows={[
        ['固定发布周期', `${DRIVE_PUBLISH_INTERVAL_MS} ms / 20Hz`],
        ['摇杆滤波', `α=${JOYSTICK_ALPHA}`],
        ['心跳保护', heartbeatProtectionEnabled ? '启用' : '已关闭（测试）'],
        ['心跳周期', `${heartbeat.intervalMs ?? HEARTBEAT_INTERVAL_MS} ms`],
        ['超时急停', heartbeatProtectionEnabled ? `${heartbeat.timeoutMs ?? WATCHDOG_TIMEOUT_MS} ms` : '已关闭'],
        ['最近心跳', heartbeat.ageMs === null || heartbeat.ageMs === undefined ? '未收到' : `${heartbeat.ageMs} ms`],
        ['运动状态', command?.active ? '运动命令活跃' : '静止'],
        ['遥控授权', canDrive ? '允许' : '锁定']
      ]} />
      <div className="drive-lock compact">
        {blockers?.length ? blockers.map((blocker) => <span key={blocker}>{translateBlocker(blocker)}</span>) : <span>所有遥控前置条件满足</span>}
      </div>
    </section>
  );
}

function AlarmPanel({ alarms, onAck, onResolve }) {
  const [statusFilter, setStatusFilter] = useState('active');
  const [severityFilter, setSeverityFilter] = useState('all');
  const items = (alarms.items ?? []).filter((item) => (
    (statusFilter === 'all' || item.status === statusFilter)
    && (severityFilter === 'all' || item.severity === severityFilter)
  ));
  return (
    <section className="panel alarm-panel">
      <PanelTitle title="报警管理" right={<span className="small-help">{alarms.summary?.active ?? 0} 活跃 / {alarms.summary?.total ?? 0} 总数</span>} />
      <div className="alarm-toolbar">
        <label>状态
          <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
            <option value="active">活跃</option>
            <option value="acknowledged">已确认</option>
            <option value="resolved">已恢复</option>
            <option value="all">全部</option>
          </select>
        </label>
        <label>级别
          <select value={severityFilter} onChange={(event) => setSeverityFilter(event.target.value)}>
            <option value="error">Error</option>
            <option value="all">全部</option>
            <option value="critical">严重</option>
            <option value="warning">警告</option>
            <option value="info">信息</option>
          </select>
        </label>
      </div>
      <div className="alarm-layout">
        <div className="alarm-list">
          {items.length === 0 ? (
            <div className="alarm-empty">当前筛选条件下没有报警</div>
          ) : items.map((alarm) => (
            <div className={`alarm-row severity-${alarm.severity}`} key={alarm.id}>
              <div>
                <strong>{alarm.title}</strong>
                <span>{alarm.message}</span>
                <small>{formatTime(alarm.lastSeenAt)} / {alarm.source} / {alarm.status} / x{alarm.count}</small>
              </div>
              <div className="alarm-actions">
                <button disabled={alarm.status !== 'active'} onClick={() => onAck(alarm.id)}>确认</button>
                <button disabled={alarm.status === 'resolved'} onClick={() => onResolve(alarm.id)}>恢复</button>
              </div>
            </div>
          ))}
        </div>
        <div className="alarm-timeline">
          {(alarms.items ?? []).slice(0, 12).map((alarm) => (
            <div key={alarm.id} className={`timeline-item severity-${alarm.severity}`}>
              <i />
              <span>{formatTime(alarm.createdAt)}</span>
              <strong>{alarm.title}</strong>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function RasterPreview({ title, sample, fallback }) {
  const canvasRef = useRef(null);
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !sample?.connected || sample.previewType === 'dataUrl') return;
    drawRasterPreview(canvas, sample);
  }, [sample]);

  return (
    <div className={`perception-card ${sample?.stale ? 'stale-visual' : ''}`}>
      <header>
        <strong>{title}</strong>
        <span className={sample?.connected && !sample?.stale ? 'ok-text' : 'bad-text'}>{sample?.stale ? '断流·保留末帧' : sample?.connected ? '在线' : '等待'}</span>
      </header>
      <div className="raster-frame">
        {sample?.connected && sample.previewType === 'dataUrl' ? (
          <img src={sample.dataUrl} alt={`${title} 预览`} />
        ) : sample?.connected ? (
          <canvas ref={canvasRef} />
        ) : (
          <div className="perception-empty">
            <Icon name="camera" />
            <span>{fallback}</span>
          </div>
        )}
      </div>
      <footer>
        <span>{sample?.topic ?? 'topic 未发现'}</span>
        <span>{sample?.connected ? formatSampleAge(sample) : sample?.width && sample?.height ? `${sample.width}x${sample.height}` : sample?.encoding ?? '无真实数据'}</span>
      </footer>
    </div>
  );
}

function PointCloudPreview({ pointCloud }) {
  const containerRef = useRef(null);
  const sceneRef = useRef(null);
  const latestCloudRef = useRef(pointCloud);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return undefined;
    let disposed = false;
    let frame = 0;
    let resize = null;

    Promise.all([
      import('three'),
      import('three/examples/jsm/controls/OrbitControls.js')
    ]).then(([THREE, controlsModule]) => {
      if (disposed || !containerRef.current) return;
      const width = container.clientWidth || 360;
      const height = container.clientHeight || 220;
      const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
      renderer.setPixelRatio(window.devicePixelRatio || 1);
      renderer.setSize(width, height);
      container.replaceChildren(renderer.domElement);

      const scene = new THREE.Scene();
      scene.background = new THREE.Color(0x081016);
      const camera = new THREE.PerspectiveCamera(55, width / height, 0.02, 80);
      camera.position.set(2.7, -3.6, 2.4);
      const controls = new controlsModule.OrbitControls(camera, renderer.domElement);
      controls.enableDamping = true;
      controls.target.set(0, 0, 0.4);
      scene.add(new THREE.GridHelper(6, 12, 0x2f4854, 0x1d2a32));
      scene.add(new THREE.AxesHelper(1.2));
      scene.add(new THREE.AmbientLight(0xffffff, 0.85));
      sceneRef.current = { THREE, scene, camera, renderer, controls, points: null };
      updatePointCloudScene(sceneRef.current, latestCloudRef.current);

      const animate = () => {
        frame = requestAnimationFrame(animate);
        controls.update();
        renderer.render(scene, camera);
      };
      animate();

      resize = () => {
        const nextWidth = container.clientWidth || width;
        const nextHeight = container.clientHeight || height;
        camera.aspect = nextWidth / nextHeight;
        camera.updateProjectionMatrix();
        renderer.setSize(nextWidth, nextHeight);
      };
      window.addEventListener('resize', resize);
    });

    return () => {
      disposed = true;
      if (resize) window.removeEventListener('resize', resize);
      cancelAnimationFrame(frame);
      sceneRef.current?.controls?.dispose();
      sceneRef.current?.renderer?.dispose();
      sceneRef.current = null;
    };
  }, []);

  useEffect(() => {
    latestCloudRef.current = pointCloud;
    updatePointCloudScene(sceneRef.current, pointCloud);
  }, [pointCloud]);

  return (
    <div className={`perception-card pointcloud-card ${pointCloud?.stale ? 'stale-visual' : ''}`}>
      <header>
        <strong>3D 点云</strong>
        <span className={pointCloud?.connected && !pointCloud?.stale ? 'ok-text' : 'bad-text'}>{pointCloud?.stale ? '断流·保留末帧' : pointCloud?.connected ? '在线' : '未启动'}</span>
      </header>
      <div ref={containerRef} className="pointcloud-frame" />
      <footer>
        <span>{pointCloud?.topic ?? '等待 PointCloud2'}</span>
        <span>{pointCloud?.connected ? `${pointCloud.sampledPoints ?? pointCloud.points?.length ?? 0}/${pointCloud.totalPoints ?? 0} 点 · ${formatSampleAge(pointCloud)}` : '无模拟场景'}</span>
      </footer>
    </div>
  );
}

function updatePointCloudScene(state, pointCloud) {
  if (!state?.THREE) return;
  const { THREE } = state;
  const points = pointCloud?.points ?? [];
  if (state.points) {
    state.scene.remove(state.points);
    state.points.geometry.dispose();
    state.points.material.dispose();
  }
  const geometry = new THREE.BufferGeometry();
  const positions = new Float32Array(points.length * 3);
  const colors = new Float32Array(points.length * 3);
  points.forEach((point, index) => {
    positions[index * 3] = point.x;
    positions[index * 3 + 1] = point.y;
    positions[index * 3 + 2] = point.z;
    const color = new THREE.Color(point.color ?? '#12c9b7');
    colors[index * 3] = color.r;
    colors[index * 3 + 1] = color.g;
    colors[index * 3 + 2] = color.b;
  });
  geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));
  const material = new THREE.PointsMaterial({ size: 0.035, vertexColors: true, opacity: pointCloud?.stale ? 0.35 : 1, transparent: true });
  state.points = new THREE.Points(geometry, material);
  state.scene.add(state.points);
}

function TrackingPreview({ tracking, perception }) {
  const twist = tracking?.shadowTwist;
  const services = perception?.services ?? {};
  return (
    <div className="perception-card tracking-card">
      <header>
        <strong>颜色 HSV / KCF / 目标追踪</strong>
        <span className={services.colorTracker ? 'ok-text' : 'warn-text'}>{services.colorTracker ? '节点运行' : '未启动'}</span>
      </header>
      <div className="tracking-body">
        {tracking?.image ? (
          <InlineRasterPreview sample={tracking.image} />
        ) : (
          <div className="perception-empty compact">
            <Icon name="scope" />
            <span>追踪输出锁定到 /tracking_cmd_vel_shadow</span>
          </div>
        )}
        <DataGrid rows={[
          ['Astra', services.astraCamera ? '运行' : '未启动'],
          ['颜色 HSV', services.colorHsv ? '运行' : '未启动'],
          ['颜色 Tracker', services.colorTracker ? '运行' : '未启动'],
          ['KCF / findObj / trackObj', '按发现的真实节点显示于能力中心'],
          ['影子线速度', twist?.linear?.x ?? null],
          ['影子角速度', twist?.angular?.z ?? null],
          ['真实 /cmd_vel', '未转发']
        ]} />
      </div>
    </div>
  );
}

function InlineRasterPreview({ sample }) {
  const canvasRef = useRef(null);
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !sample?.connected || sample.previewType === 'dataUrl') return;
    drawRasterPreview(canvas, sample);
  }, [sample]);
  return (
    <div className="inline-raster">
      {sample?.previewType === 'dataUrl' ? <img src={sample.dataUrl} alt="追踪图像" /> : <canvas ref={canvasRef} />}
    </div>
  );
}

function RecordingPanel({ recording, recordings, topicOptions, selectedTopics, onToggleTopic, onStart, onStop, onDelete, busy }) {
  const options = topicOptions.length > 0 ? topicOptions : DEFAULT_RECORD_TOPICS.map((topic) => ({ role: topic, label: topic, topic }));
  return (
    <div className="perception-card recording-card">
      <header>
        <strong>rosbag2 记录</strong>
        <span className={recording?.active ? 'ok-text' : 'warn-text'}>{recording?.active ? '录制中' : '待机'}</span>
      </header>
      <div className="recording-controls">
        <button disabled={Boolean(busy) || recording?.active} onClick={onStart}><Icon name="play" />开始</button>
        <button disabled={Boolean(busy) || !recording?.active} onClick={onStop}><Icon name="square" />停止并同步</button>
      </div>
      <div className="topic-picker">
        {options.map((option) => (
          <label key={option.topic}>
            <input
              type="checkbox"
              checked={selectedTopics.includes(option.topic)}
              onChange={() => onToggleTopic(option.topic)}
            />
            <span>{option.label}</span>
            <small>{option.topic}</small>
          </label>
        ))}
      </div>
      <DataGrid rows={[
        ['会话', recording?.sessionId],
        ['Topic 数', selectedTopics.length],
        ['本地大小', formatBytes(recording?.sizeBytes)],
        ['可用空间', formatBytes(recording?.diskFreeBytes)],
        ['本地路径', recording?.localPath],
        ['错误', recording?.lastError]
      ]} />
      <div className="recording-list">
        {recordings.length === 0 ? (
          <span>暂无本地录制</span>
        ) : recordings.slice(0, 4).map((item) => (
          <div key={item.id}>
            <strong>{item.id}</strong>
            <small>{formatBytes(item.sizeBytes)} / {item.fileCount} 文件</small>
            <a href={`/api/recordings/${encodeURIComponent(item.id)}/download`}>下载</a>
            <button onClick={() => onDelete(item.id)} title="删除录制"><Icon name="trash" /></button>
          </div>
        ))}
      </div>
    </div>
  );
}

function Joystick({
  disabled,
  driveReady = !disabled,
  emergencyStopActive = false,
  blockers = [],
  busy,
  title = '摇杆',
  compact = false,
  vector,
  keyboardActive,
  onVector,
  onStop,
  onResume
}) {
  const padRef = useRef(null);
  const activeRef = useRef(false);
  const statusLabel = emergencyStopActive ? '急停锁定' : disabled ? '锁定' : keyboardActive ? '键盘控制中' : '就绪';
  const statusText = emergencyStopActive
    ? '急停已触发，恢复后才会接受运动命令'
    : blockers?.length
      ? translateBlocker(blockers[0])
      : disabled
        ? '等待遥控前置条件'
        : '拖动摇杆发布 /cmd_vel_manual';

  const updateFromEvent = useCallback((event) => {
    if (!activeRef.current || disabled) return;
    const rect = padRef.current.getBoundingClientRect();
    const cx = rect.left + rect.width / 2;
    const cy = rect.top + rect.height / 2;
    const max = rect.width * 0.42;
    const dx = Math.max(-max, Math.min(max, event.clientX - cx));
    const dy = Math.max(-max, Math.min(max, event.clientY - cy));
    onVector({
      forward: roundClient(-dy / max),
      turn: roundClient(dx / max),
      strafe: 0
    });
  }, [disabled, onVector]);

  const stopPointer = useCallback((event) => {
    activeRef.current = false;
    event?.currentTarget?.releasePointerCapture?.(event.pointerId);
    onStop();
  }, [onStop]);

  return (
    <section className={`panel joystick-panel ${compact ? 'compact' : ''} ${disabled ? 'disabled' : ''}`}>
      <PanelTitle
        title={title}
        right={(
          <span className={`keyboard-status ${emergencyStopActive ? 'danger' : ''}`} title="W/S 前后，A/D 转向，Q/E 横移，空格急停">
            <Icon name="keyboard" />
            {statusLabel}
          </span>
        )}
      />
      <div
        ref={padRef}
        className="joystick-pad"
        onPointerDown={(event) => {
          if (disabled) return;
          activeRef.current = true;
          event.currentTarget.setPointerCapture(event.pointerId);
          updateFromEvent(event);
        }}
        onPointerMove={updateFromEvent}
        onPointerUp={stopPointer}
        onPointerCancel={stopPointer}
      >
        <span className="arrow up">^</span>
        <span className="arrow down">v</span>
        <span className="arrow left">&lt;</span>
        <span className="arrow right">&gt;</span>
        <div
          className="stick"
          style={{
            transform: `translate(${vector.turn * (compact ? 40 : 45)}px, ${-vector.forward * (compact ? 40 : 45)}px)`
          }}
        />
      </div>
      <div className="joystick-readout">
        <span>前后 <strong>{vector.forward.toFixed(2)}</strong></span>
        <span>转向 <strong>{vector.turn.toFixed(2)}</strong></span>
        <span>横移 <strong>{(vector.strafe ?? 0).toFixed(2)}</strong></span>
      </div>
      {(compact || emergencyStopActive || blockers?.length > 0) && (
        <div className={`joystick-status ${emergencyStopActive ? 'locked' : ''}`}>
          <span>{statusText}</span>
          {emergencyStopActive && onResume && (
            <button type="button" onClick={onResume} disabled={busy === 'resume'}>
              <Icon name="play" />
              {busy === 'resume' ? '恢复中' : '恢复遥控'}
            </button>
          )}
        </div>
      )}
    </section>
  );
}

function SpeedPanel({
  linearLimit,
  angularLimit,
  maxLinear,
  maxAngular,
  setLinearLimit,
  setAngularLimit,
  onEmergency,
  disabled
}) {
  return (
    <section className="panel speed-panel">
      <PanelTitle title="速度上限" right={<span className="small-help">{disabled ? '运动锁定' : '低速模式'}</span>} />
      <label className="slider-row">
        <span>线速度</span>
        <input type="range" min="0.05" max={maxLinear} step="0.01" value={linearLimit} onChange={(event) => setLinearLimit(Number(event.target.value))} />
        <strong>{linearLimit.toFixed(2)} m/s</strong>
      </label>
      <label className="slider-row">
        <span>角速度</span>
        <input type="range" min="0.10" max={maxAngular} step="0.05" value={angularLimit} onChange={(event) => setAngularLimit(Number(event.target.value))} />
        <strong>{angularLimit.toFixed(2)} rad/s</strong>
      </label>
      <button className="emergency-button" onClick={onEmergency}>
        <Icon name="stop" />
        急停
      </button>
    </section>
  );
}

function ServiceActions({ busy, onStart, onStop, onRefresh }) {
  return (
    <section className="panel action-panel">
      <PanelTitle title="服务控制" />
      <div className="action-grid">
        <button className="primary-action" disabled={Boolean(busy)} onClick={onStart}>
          <Icon name="play" />
          {busy === 'start' ? '启动中' : '启动全部'}
        </button>
        <button className="danger-action" disabled={Boolean(busy)} onClick={onStop}>
          <Icon name="square" />
          {busy === 'stop' ? '停止中' : '停止全部'}
        </button>
        <button onClick={onRefresh}>
          <Icon name="refresh" />
          刷新
        </button>
        <button disabled>
          <Icon name="power" />
          关闭小车
        </button>
      </div>
    </section>
  );
}

function NavigationActions({
  navigation,
  profile,
  busy,
  onStart,
  onCancel,
  onReturnHome,
  onSimulateLowBattery,
  onResetSafety
}) {
  const patrol = navigation?.patrol ?? {};
  const routeReady = patrol.routeConfigured === true;
  const safetyReady = navigation?.safetyState === 'READY';
  return (
    <section className="panel action-panel">
      <PanelTitle title="Navigation / Patrol" />
      <div className="action-grid">
        <button disabled={Boolean(busy) || !routeReady || !safetyReady} onClick={onStart}>
          <Icon name="play" />
          Start patrol
        </button>
        <button disabled={Boolean(busy)} onClick={onCancel}>
          <Icon name="square" />
          Cancel patrol
        </button>
        <button disabled={Boolean(busy) || !routeReady || !safetyReady} onClick={onReturnHome}>
          <Icon name="home" />
          Return Home
        </button>
        <button disabled={Boolean(busy) || !routeReady || !safetyReady} onClick={onSimulateLowBattery}>
          <Icon name="power" />
          Simulate low battery
        </button>
        <button disabled={Boolean(busy)} onClick={onResetSafety}>
          <Icon name="refresh" />
          Reset safety
        </button>
      </div>
      <small>
        {`Profile ${profile?.mode ?? 'safe_base'} · Safety ${navigation?.safetyState ?? 'UNKNOWN'} · Source ${navigation?.activeSource ?? 'UNKNOWN'} · Patrol ${patrol.state ?? 'UNKNOWN'} · ${routeReady ? 'route ready' : 'route not configured'}`}
      </small>
      {navigation?.lastService && (
        <small className={navigation.lastService.success ? 'ok-text' : 'bad-text'}>
          {`${navigation.lastService.service}: ${navigation.lastService.success ? 'accepted' : 'rejected'} — ${navigation.lastService.message}`}
        </small>
      )}
    </section>
  );
}

function SensorInspector({ telemetry, status, command, blockers, telemetryOnline }) {
  const voltageFresh = telemetryOnline && isTelemetryFresh(telemetry.voltage);
  const mainBatteryPercent = voltageFresh ? batteryPercent(telemetry.voltage) : null;
  const voltageUnavailable = telemetry.voltage.invalidReason
    ? `无效 ${fmt(telemetry.voltage.rawBattery, ' V')}`
    : telemetry.voltage.connected ? '遥测过期' : '未连接';
  const mainBatteryLabel = voltageFresh ? formatPercent(mainBatteryPercent) : voltageUnavailable;
  return (
    <aside className="inspector panel">
      <h2>传感器面板</h2>
      <SensorCard title="IMU 姿态" connected={telemetry.imu.connected}>
        <DataGrid rows={[
          ['航向角 deg', telemetry.imu.orientation.yaw],
          ['横滚角 deg', telemetry.imu.orientation.roll],
          ['俯仰角 deg', telemetry.imu.orientation.pitch],
          ['加速度 X', telemetry.imu.acceleration.x],
          ['加速度 Y', telemetry.imu.acceleration.y],
          ['加速度 Z', telemetry.imu.acceleration.z],
          ['角速度 X', telemetry.imu.gyro.x],
          ['角速度 Y', telemetry.imu.gyro.y],
          ['角速度 Z', telemetry.imu.gyro.z],
          ['磁力计 X', telemetry.imu.magnetometer.x],
          ['磁力计 Y', telemetry.imu.magnetometer.y],
          ['磁力计 Z', telemetry.imu.magnetometer.z]
        ]} />
      </SensorCard>
      <SensorCard
        title="电源与电量"
        connected={voltageFresh}
        reason={voltageFresh ? '仅显示 /voltage 的真实主电池电压；百分比是 9.6–12.6V 区间估算。' : `主车 /voltage ${voltageUnavailable}`}
      >
        <DataGrid rows={[
          ['主车电池电压', voltageFresh ? fmt(telemetry.voltage.battery, ' V') : voltageUnavailable],
          ['主车电量（估算）', mainBatteryLabel],
          ['数据年龄', formatSampleAge(telemetry.voltage)]
        ]} />
        <BatteryBar percent={mainBatteryPercent} label={mainBatteryLabel} />
      </SensorCard>
      <SensorCard title="速度" connected={telemetry.velocity.connected}>
        <DataGrid rows={[
          ['线速度 m/s', telemetry.velocity.linear],
          ['反馈角速度 rad/s', telemetry.velocity.angular],
          ['命令角速度 rad/s', command?.lastTwist?.angular?.z ?? null],
          ['直行补偿 rad/s', command?.straightAssist?.correctionAngular ?? null],
          ['直行辅助', formatStraightAssist(command?.straightAssist)]
        ]} />
      </SensorCard>
      {!status.canDrive && (
        <div className="drive-lock">
          <strong>运动锁定</strong>
          {blockers.map((blocker) => <span key={blocker}>{translateBlocker(blocker)}</span>)}
        </div>
      )}
    </aside>
  );
}

function SensorCard({ title, connected, reason, children }) {
  return (
    <section className="sensor-card">
      <header>
        <strong>{title}</strong>
        <span className={connected ? 'ok-text' : 'bad-text'}>{connected ? '正常' : '未连接'}</span>
      </header>
      {reason && <p>{reason}</p>}
      {children}
    </section>
  );
}

function DataGrid({ rows }) {
  return (
    <div className="data-grid">
      {rows.map(([label, value]) => (
        <div key={label}>
          <span>{label}</span>
          <strong>{value === null || value === undefined || value === 'Not connected' || value === '未连接' ? '未连接' : value}</strong>
        </div>
      ))}
    </div>
  );
}

function BatteryBar({ percent, label }) {
  const width = percent == null ? 0 : Math.max(0, Math.min(100, percent));
  return (
    <div className="battery-bar">
      <span style={{ width: `${width}%` }} />
      {label && <strong>{label}</strong>}
    </div>
  );
}

function LogConsole({ logs }) {
  const listRef = useRef(null);
  useEffect(() => {
    const element = listRef.current;
    if (element) element.scrollTop = element.scrollHeight;
  }, [logs]);
  return (
    <section className="panel log-panel">
      <PanelTitle
        title="日志控制台"
        right={(
          <div className="log-tools">
            <button>清空</button>
            <button>暂停</button>
            <label><input type="checkbox" checked readOnly /> 自动滚动</label>
            <button><Icon name="trash" /></button>
          </div>
        )}
      />
      <div ref={listRef} className="log-list">
        {logs.length === 0 ? (
          <pre><span className="log-muted">等待 API 事件...</span></pre>
        ) : logs.slice(-80).map((log) => (
          <pre key={log.id}>
            <span>{new Date(log.ts).toLocaleTimeString()}</span>
            <span className={`log-${log.level}`}>[{log.level.toUpperCase()}]</span>
            <span>[{log.scope}]</span>
            <span>{log.message}</span>
          </pre>
        ))}
      </div>
    </section>
  );
}

function ConfigDialog({ config, onClose, onSaved }) {
  const [form, setForm] = useState({
    host: config.car.host,
    sshUser: config.car.sshUser,
    sshPassword: ''
  });
  const [saving, setSaving] = useState(false);

  async function save(event) {
    event.preventDefault();
    setSaving(true);
    try {
      const response = await fetch('/api/config', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          car: {
            host: form.host,
            sshUser: form.sshUser,
            sshPassword: form.sshPassword
          }
        })
      });
      const body = await response.json();
      if (body.config) onSaved(body.config);
      onClose();
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="dialog-backdrop" role="presentation">
      <form className="dialog panel" onSubmit={save}>
        <PanelTitle title="连接设置" right={<button type="button" className="icon-button" onClick={onClose}><Icon name="square" /></button>} />
        <label>
          <span>小车 IP</span>
          <input value={form.host} onChange={(event) => setForm({ ...form, host: event.target.value })} />
        </label>
        <label>
          <span>SSH 用户</span>
          <input value={form.sshUser} onChange={(event) => setForm({ ...form, sshUser: event.target.value })} />
        </label>
        <label>
          <span>SSH 密码</span>
          <input type="password" placeholder={config.car.sshPasswordSet ? '已保存密码' : ''} value={form.sshPassword} onChange={(event) => setForm({ ...form, sshPassword: event.target.value })} />
        </label>
        <label>
          <span>SSH 主机密钥</span>
          <small>仅可在 local-config.json 中设置</small>
        </label>
        <label>
          <span>Plink 路径</span>
          <small>仅可在 local-config.json 中设置</small>
        </label>
        <div className="dialog-actions">
          <button type="button" onClick={onClose}>取消</button>
          <button className="primary-action" disabled={saving}>{saving ? '保存中' : '保存'}</button>
        </div>
      </form>
    </div>
  );
}

function PanelTitle({ title, right }) {
  return (
    <header className="panel-title">
      <h2>{title}</h2>
      {right && <div>{right}</div>}
    </header>
  );
}

function ToolbarIcons({ names }) {
  const titles = {
    camera: '截图',
    fullscreen: '全屏',
    more: '更多'
  };
  return (
    <div className="toolbar-icons">
      {names.map((name) => <button key={name} title={titles[name] ?? name}><Icon name={name} /></button>)}
    </div>
  );
}

function drawRasterPreview(canvas, sample) {
  const width = sample.previewWidth || sample.width || 96;
  const height = sample.previewHeight || sample.height || 72;
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext('2d');
  const image = ctx.createImageData(width, height);
  if (sample.previewType === 'rgbPixels') {
    sample.pixels?.forEach((pixel, index) => {
      image.data[index * 4] = pixel[0] ?? 0;
      image.data[index * 4 + 1] = pixel[1] ?? 0;
      image.data[index * 4 + 2] = pixel[2] ?? 0;
      image.data[index * 4 + 3] = 255;
    });
  } else {
    const values = sample.values ?? [];
    const min = Number.isFinite(sample.min) ? sample.min : 0;
    const max = Number.isFinite(sample.max) && sample.max > min ? sample.max : min + 1;
    values.forEach((value, index) => {
      const normalized = value === null || value === undefined ? 0 : Math.max(0, Math.min(1, (value - min) / (max - min)));
      const [r, g, b] = sample.role === 'ir' ? grayColor(normalized) : depthColor(normalized);
      image.data[index * 4] = r;
      image.data[index * 4 + 1] = g;
      image.data[index * 4 + 2] = b;
      image.data[index * 4 + 3] = 255;
    });
  }
  ctx.putImageData(image, 0, 0);
}

function depthColor(value) {
  const hue = 235 - value * 235;
  return hslToRgb(hue, 92, 52);
}

function grayColor(value) {
  const gray = Math.round(value * 255);
  return [gray, gray, gray];
}

function hslToRgb(h, s, l) {
  s /= 100;
  l /= 100;
  const k = (n) => (n + h / 30) % 12;
  const a = s * Math.min(l, 1 - l);
  const f = (n) => l - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1)));
  return [f(0), f(8), f(4)].map((value) => Math.round(255 * value));
}

function recordingTopicOptions(perception) {
  const matches = perception?.topicDiscovery?.matches ?? {};
  const discovered = Object.values(matches)
    .filter((match) => match?.topic && match.role !== 'cameraInfo')
    .map((match) => ({ role: match.role, label: match.label ?? match.role, topic: match.topic }));
  const defaults = DEFAULT_RECORD_TOPICS.map((topic) => ({ role: topic, label: topic, topic }));
  const byTopic = new Map(defaults.map((item) => [item.topic, item]));
  for (const item of discovered) byTopic.set(item.topic, item);
  return [...byTopic.values()];
}

function formatBytes(value) {
  const bytes = Number(value);
  if (!Number.isFinite(bytes) || bytes <= 0) return '未连接';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let size = bytes;
  let index = 0;
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024;
    index += 1;
  }
  return `${size.toFixed(size >= 10 || index === 0 ? 0 : 1)} ${units[index]}`;
}

function formatTime(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '未知时间';
  return date.toLocaleTimeString('zh-CN', { hour12: false });
}

function formatDateTime(value) {
  if (!value) return '尚未确认';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '尚未确认';
  return date.toLocaleString('zh-CN', { hour12: false });
}

function formatSampleAge(sample) {
  if (Number.isFinite(Number(sample?.ageMs))) {
    const age = Number(sample.ageMs);
    return age < 1000 ? `${Math.round(age)} ms` : `${(age / 1000).toFixed(1)} s${sample?.stale ? ' · 已过期' : ''}`;
  }
  return sample?.updatedAt ? formatDateTime(sample.updatedAt) : '尚未采样';
}

function formatTopicActivity(activity) {
  if (!activity) return '未收到';
  const hz = Number.isFinite(Number(activity.frequencyHz)) ? `${Number(activity.frequencyHz).toFixed(1)} Hz` : '频率待计算';
  return `${hz} / ${formatSampleAge(activity)}`;
}

function capabilityStatus(capabilities, key) {
  const item = capabilities?.items?.[key];
  if (!item) return '待探测';
  const availability = { SUPPORTED: '已具备', UNSUPPORTED: '不支持', UNKNOWN: '待确认' }[item.availability] ?? item.availability;
  const runtimeLabel = { ACTIVE: '运行中', INACTIVE: '未运行', STALE: '证据过期', ERROR: '探测失败' }[item.runtime] ?? item.runtime;
  return `${availability} / ${runtimeLabel}`;
}

function detectionAlgorithmName(topic) {
  const lower = String(topic ?? '').toLowerCase();
  if (!lower) return '未发现真实检测 topic';
  if (lower.includes('yolo')) return 'YOLO 检测';
  if (lower.includes('face')) return 'MediaPipe 人脸检测';
  if (lower.includes('hand')) return 'MediaPipe 手势检测';
  if (lower.includes('pose')) return 'MediaPipe 姿态检测';
  return `Topic 实际算法（${topic}）`;
}

function fmt(value, suffix = '') {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '未连接';
  return `${Number(value).toFixed(Math.abs(value) >= 10 ? 1 : 2)}${suffix}`;
}

function formatBatterySummary(voltage, fresh = isTelemetryFresh(voltage)) {
  if (!fresh) {
    if (voltage?.invalidReason) return '无有效电压';
    return voltage?.connected ? '遥测过期' : '未连接';
  }
  const battery = fmt(voltage?.battery, ' V');
  if (battery === '未连接') return battery;
  const percent = batteryPercent(voltage);
  return percent === null ? battery : `${battery} / 估算${percent}%`;
}

function isTelemetryFresh(sample, maxAgeMs = TELEMETRY_STALE_MS) {
  if (!sample?.connected) return false;
  const updatedAt = Date.parse(sample.updatedAt ?? '');
  if (!Number.isFinite(updatedAt)) return false;
  return Date.now() - updatedAt <= maxAgeMs;
}

function batteryPercent(voltage) {
  const estimated = estimateBatteryPercent(voltage?.battery ?? voltage?.voltage);
  if (estimated !== null) return estimated;
  const direct = Number(voltage?.percent);
  return Number.isFinite(direct) ? Math.max(0, Math.min(100, Math.round(direct))) : null;
}

function estimateBatteryPercent(value) {
  const voltage = Number(value);
  if (!Number.isFinite(voltage)) return null;
  const emptyVoltage = 9.6;
  const fullVoltage = 12.6;
  return Math.max(0, Math.min(100, Math.round((voltage - emptyVoltage) / (fullVoltage - emptyVoltage) * 100)));
}

function formatPercent(value) {
  return value === null || value === undefined ? '未连接' : `${value}%`;
}

function translateBlocker(blocker) {
  const translations = {
    'Chassis serial device is missing': '底盘串口设备缺失',
    'Chassis driver is not running': '底盘驱动未运行',
    'RPLidar device is missing': '雷达设备缺失',
    'Lidar driver is not running': '雷达驱动未运行',
    'Camera device is missing': '摄像头设备缺失',
    'Camera stream is not running': '摄像头视频流未运行',
    'ROSBridge is not connected': 'ROSBridge 未连接',
    'Status has not been refreshed': '状态尚未刷新',
    'Waiting for status check': '等待状态检查'
  };
  return translations[blocker] ?? blocker;
}

function formatStraightAssist(assist) {
  if (!assist || assist.enabled === false) return '关闭';
  if (assist.active) return '校正中';
  const labels = {
    disabled: '关闭',
    below_min_forward: '待机',
    manual_axis: '手动转向',
    angular_limit_zero: '角速度限幅为 0',
    no_feedback: '等待反馈',
    stale_feedback: '反馈过期',
    within_dead_zone: '无需校正',
    correcting: '校正中'
  };
  return labels[assist.reason] ?? '待机';
}

function roundClient(value) {
  return Math.round(value * 100) / 100;
}

function Icon({ name }) {
  const paths = {
    car: <><path d="M4 13l2-5h12l2 5" /><path d="M5 13h14v5H5z" /><circle cx="8" cy="18" r="1.6" /><circle cx="16" cy="18" r="1.6" /></>,
    home: <><path d="M4 11l8-7 8 7" /><path d="M6 10v10h12V10" /><path d="M10 20v-6h4v6" /></>,
    scope: <><path d="M5 18h14" /><path d="M7 15l3-7 4 5 3-9" /><circle cx="7" cy="15" r="1" /><circle cx="17" cy="4" r="1" /></>,
    map: <><path d="M5 5l5-2 4 2 5-2v16l-5 2-4-2-5 2z" /><path d="M10 3v16" /><path d="M14 5v16" /></>,
    terminal: <><path d="M5 7l5 5-5 5" /><path d="M12 17h7" /></>,
    clipboard: <><path d="M8 5h8v3H8z" /><path d="M6 7h12v13H6z" /></>,
    settings: <><circle cx="12" cy="12" r="3" /><path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M18.4 5.6l-2.1 2.1M7.7 16.3l-2.1 2.1" /></>,
    play: <path d="M8 5l10 7-10 7z" />,
    square: <path d="M7 7h10v10H7z" />,
    stop: <path d="M7 7h10v10H7z" />,
    refresh: <><path d="M19 8a7 7 0 10-2 7" /><path d="M19 4v4h-4" /></>,
    power: <><path d="M12 3v9" /><path d="M6.5 7.5a7 7 0 1011 0" /></>,
    camera: <><path d="M5 8h3l1.5-2h5L16 8h3v10H5z" /><circle cx="12" cy="13" r="3" /></>,
    fullscreen: <><path d="M5 9V5h4M15 5h4v4M19 15v4h-4M9 19H5v-4" /></>,
    more: <><circle cx="12" cy="6" r="1" /><circle cx="12" cy="12" r="1" /><circle cx="12" cy="18" r="1" /></>,
    trash: <><path d="M6 7h12" /><path d="M9 7V5h6v2" /><path d="M8 7l1 13h6l1-13" /></>,
    save: <><path d="M5 5h12l2 2v12H5z" /><path d="M8 5v6h8V5" /><path d="M8 19v-5h8v5" /></>,
    chip: <><rect x="7" y="7" width="10" height="10" rx="2" /><path d="M4 10h3M4 14h3M17 10h3M17 14h3M10 4v3M14 4v3M10 17v3M14 17v3" /></>
    ,
    keyboard: <><path d="M4 7h16v10H4z" /><path d="M7 10h.1M10 10h.1M13 10h.1M16 10h.1M7 13h6M16 13h1" /></>
  };
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      {paths[name] ?? paths.chip}
    </svg>
  );
}
