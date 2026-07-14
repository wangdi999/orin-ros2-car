import { EventEmitter } from 'node:events';

export const bus = new EventEmitter();

function inactiveStraightAssist(reason = null) {
  return {
    enabled: false,
    active: false,
    reason,
    feedbackAngular: null,
    feedbackAgeMs: null,
    correctionAngular: 0,
    updatedAt: null
  };
}

export const telemetry = {
  lidar: {
    connected: false,
    frameId: null,
    rangeMax: 12,
    points: [],
    updatedAt: null
  },
  imu: {
    connected: false,
    orientation: { roll: null, pitch: null, yaw: null },
    acceleration: { x: null, y: null, z: null },
    gyro: { x: null, y: null, z: null },
    magnetometer: { x: null, y: null, z: null },
    updatedAt: null
  },
  voltage: {
    connected: false,
    battery: null,
    rawBattery: null,
    percent: null,
    percentEstimated: true,
    invalidReason: null,
    updatedAt: null
  },
  velocity: {
    connected: false,
    linear: null,
    angular: null,
    updatedAt: null
  },
  map: {
    connected: false,
    mode: null,
    frameId: null,
    width: null,
    height: null,
    previewWidth: null,
    previewHeight: null,
    step: null,
    resolution: null,
    origin: { x: null, y: null, yaw: null },
    occupied: 0,
    free: 0,
    unknown: 0,
    cells: [],
    updatedAt: null
  },
  globalCostmap: emptyGrid(),
  localCostmap: emptyGrid(),
  globalPath: emptyPath(),
  localPath: emptyPath(),
  patrolRoute: emptyPath(),
  odometry: emptyPose('odom'),
  amclPose: emptyPose('map'),
  tfPose: emptyPose('map'),
  pose: {
    connected: false,
    frameId: null,
    childFrameId: null,
    pose: { x: null, y: null, yaw: null },
    linear: null,
    angular: null,
    updatedAt: null
  },
  camera: {
    connected: false,
    topic: null,
    type: null,
    previewType: null,
    dataUrl: null,
    width: null,
    height: null,
    encoding: null,
    pixels: [],
    updatedAt: null
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
    values: [],
    updatedAt: null
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
    values: [],
    updatedAt: null
  },
  pointCloud: {
    connected: false,
    topic: null,
    type: null,
    frameId: null,
    width: null,
    height: null,
    totalPoints: 0,
    sampledPoints: 0,
    bounds: null,
    points: [],
    updatedAt: null
  },
  tracking: {
    connected: false,
    imageTopic: null,
    velocityTopic: '/tracking_cmd_vel_shadow',
    image: null,
    shadowTwist: null,
    updatedAt: null
  },
  detections: {
    connected: false,
    topic: null,
    type: null,
    frameId: null,
    sourceWidth: 640,
    sourceHeight: 480,
    count: 0,
    detections: [],
    lastError: null,
    updatedAt: null
  }
};

function emptyGrid() {
  return {
    connected: false,
    mode: 'map',
    frameId: null,
    width: null,
    height: null,
    previewWidth: null,
    previewHeight: null,
    step: null,
    resolution: null,
    origin: { x: null, y: null, yaw: null },
    cells: [],
    updatedAt: null
  };
}

function emptyPath() {
  return {
    connected: false,
    empty: true,
    frameId: null,
    totalPoints: 0,
    points: [],
    updatedAt: null
  };
}

function emptyPose(frameId) {
  return {
    connected: false,
    frameId,
    childFrameId: 'base_footprint',
    source: null,
    pose: { x: null, y: null, yaw: null },
    updatedAt: null
  };
}

export const runtime = {
  startedByConsole: false,
  capabilities: {
    schemaVersion: 1,
    target: 'X3',
    groups: [],
    detectedAt: null,
    stale: true,
    error: '能力尚未探测',
    evidence: null,
    items: {}
  },
  rosbridge: {
    connected: false,
    url: null,
    lastError: null,
    updatedAt: null
  },
  command: {
    lastDriveAt: null,
    active: false,
    lastTwist: null,
    straightAssist: inactiveStraightAssist(),
    heartbeat: {
      connected: false,
      lastAt: null,
      ageMs: null,
      intervalMs: 100,
      timeoutMs: 500,
      protectionEnabled: true
    }
  },
  safety: {
    emergencyStopActive: false,
    lastStopAt: null,
    lastStopReason: null
  },
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
    action: {
      status: 'UNKNOWN',
      activeGoals: 0,
      updatedAt: null
    },
    goal: {
      state: 'UNKNOWN',
      mode: null,
      waypoint: null,
      index: null,
      attempt: null,
      routeConfigured: false,
      reason: null,
      goalId: null
    },
    lastService: null,
    updatedAt: null
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
    lastConfiguredAt: null,
    updatedAt: null
  },
  alarms: {
    items: [],
    summary: {
      total: 0,
      active: 0,
      acknowledged: 0,
      resolved: 0,
      critical: 0,
      warning: 0
    },
    updatedAt: null
  },
  topicActivity: {},
  status: {
    local: {
      api: true,
      uptimeStartedAt: new Date().toISOString()
    },
    ssh: {
      connected: false,
      hostname: null,
      lastError: null,
      updatedAt: null
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
      arbiter: false,
      lidar: false,
      camera: false,
      rosbridge: false,
      video: false
    },
    canDrive: false,
    blockers: ['Status has not been refreshed'],
    updatedAt: null
  },
  logs: []
};

export function addLog(level, scope, message, detail = null) {
  const entry = {
    id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
    ts: new Date().toISOString(),
    level,
    scope,
    message,
    detail
  };
  runtime.logs.push(entry);
  if (runtime.logs.length > 240) runtime.logs.shift();
  bus.emit('log', entry);
  return entry;
}

export function updateStatus(status) {
  runtime.status = {
    ...runtime.status,
    ...status,
    updatedAt: new Date().toISOString()
  };
  bus.emit('snapshot', snapshot());
}

export function updateCapabilities(capabilities) {
  runtime.capabilities = capabilities;
  bus.emit('snapshot', snapshot());
}

export function updateTelemetry(partial) {
  const updated = {};
  for (const [key, value] of Object.entries(partial)) {
    telemetry[key] = {
      ...telemetry[key],
      ...value,
      updatedAt: Object.hasOwn(value, 'updatedAt') ? value.updatedAt : new Date().toISOString()
    };
    updated[key] = telemetry[key];
  }
  bus.emit('telemetry', updated);
}

export function clearMappingTelemetry() {
  updateTelemetry({
    map: {
      connected: false,
      mode: null,
      frameId: null,
      width: null,
      height: null,
      previewWidth: null,
      previewHeight: null,
      step: null,
      resolution: null,
      origin: { x: null, y: null, yaw: null },
      occupied: 0,
      free: 0,
      unknown: 0,
      cells: [],
      updatedAt: null
    },
    globalCostmap: emptyGrid(),
    localCostmap: emptyGrid(),
    globalPath: emptyPath(),
    localPath: emptyPath(),
    patrolRoute: emptyPath(),
    amclPose: emptyPose('map'),
    tfPose: emptyPose('map'),
    pose: {
      connected: false,
      frameId: 'map',
      childFrameId: 'base_footprint',
      source: null,
      pose: { x: null, y: null, yaw: null },
      linear: null,
      angular: null,
      updatedAt: null
    }
  });
}

export function clearPerceptionTelemetry() {
  updateTelemetry({
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
      width: null,
      height: null,
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
      frameId: null,
      sourceWidth: 640,
      sourceHeight: 480,
      count: 0,
      detections: [],
      lastError: null
    }
  });
}

export function updateRosbridge(partial) {
  runtime.rosbridge = {
    ...runtime.rosbridge,
    ...partial,
    updatedAt: new Date().toISOString()
  };
  recomputeCanDrive();
  bus.emit('runtime-patch', {
    rosbridge: runtime.rosbridge,
    status: { canDrive: runtime.status.canDrive, blockers: runtime.status.blockers }
  });
}

export function updateNavigation(partial) {
  const patrol = partial.patrol
    ? { ...runtime.navigation.patrol, ...partial.patrol }
    : runtime.navigation.patrol;
  runtime.navigation = {
    ...runtime.navigation,
    ...partial,
    patrol,
    updatedAt: new Date().toISOString()
  };
  if (partial.safetyState === 'ESTOP') {
    runtime.safety.emergencyStopActive = true;
  }
  recomputeCanDrive();
  bus.emit('runtime-patch', {
    navigation: runtime.navigation,
    safety: runtime.safety,
    status: { canDrive: runtime.status.canDrive, blockers: runtime.status.blockers }
  });
}

export function updatePerception(partial) {
  runtime.perception = {
    ...runtime.perception,
    ...partial,
    services: {
      ...runtime.perception.services,
      ...(partial.services ?? {})
    },
    topicDiscovery: {
      ...runtime.perception.topicDiscovery,
      ...(partial.topicDiscovery ?? {})
    },
    updatedAt: new Date().toISOString()
  };
  bus.emit('snapshot', snapshot());
}

export function updateRecording(partial) {
  runtime.recording = {
    ...runtime.recording,
    ...partial,
    updatedAt: new Date().toISOString()
  };
  bus.emit('snapshot', snapshot());
}

export function updateVideo(partial) {
  runtime.video = {
    ...runtime.video,
    ...partial,
    updatedAt: new Date().toISOString()
  };
  bus.emit('snapshot', snapshot());
}

export function updateTopicActivity(topic, observedAt = new Date().toISOString()) {
  const previous = runtime.topicActivity[topic];
  const previousAt = Date.parse(previous?.lastAt);
  const currentAt = Date.parse(observedAt);
  const intervalMs = Number.isFinite(previousAt) && Number.isFinite(currentAt)
    ? Math.max(1, currentAt - previousAt)
    : null;
  const instantHz = intervalMs === null ? null : 1000 / intervalMs;
  runtime.topicActivity[topic] = {
    topic,
    messages: (previous?.messages ?? 0) + 1,
    frequencyHz: instantHz === null
      ? previous?.frequencyHz ?? null
      : Math.round(((previous?.frequencyHz ?? instantHz) * 0.75 + instantHz * 0.25) * 10) / 10,
    lastAt: observedAt,
    ageMs: 0,
    stale: false
  };
  bus.emit('runtime-patch', { topicActivity: { [topic]: runtime.topicActivity[topic] } });
}

export function updateHeartbeat(partial = {}) {
  const lastAt = partial.lastAt ?? new Date().toISOString();
  runtime.command.heartbeat = {
    ...runtime.command.heartbeat,
    ...partial,
    connected: partial.connected ?? true,
    lastAt,
    ageMs: 0
  };
  bus.emit('runtime-patch', { command: { heartbeat: runtime.command.heartbeat } });
}

export function configureHeartbeat(partial = {}) {
  runtime.command.heartbeat = {
    ...runtime.command.heartbeat,
    ...partial
  };
  bus.emit('snapshot', snapshot());
}

export function updateAlarms(partial) {
  runtime.alarms = {
    ...runtime.alarms,
    ...partial,
    updatedAt: partial.updatedAt ?? new Date().toISOString()
  };
  bus.emit('runtime-patch', { alarms: runtime.alarms });
}

export function recomputeCanDrive() {
  const blockers = [];
  const { devices, services } = runtime.status;
  const rosbridgeConnected = runtime.rosbridge.connected;
  const cameraDeviceAvailable = devices.video0 || (devices.cameraDepth && devices.cameraUvc);
  const cameraStreamAvailable = runtime.status.ports.video6500 || services.video || services.camera;

  if (!devices.chassisSerial) blockers.push('Chassis serial device is missing');
  if (devices.chassisSerial && !services.chassis) blockers.push('Chassis driver is not running');
  if (!services.arbiter) blockers.push('Safe command arbiter is not running');
  if (!devices.lidar) blockers.push('RPLidar device is missing');
  if (devices.lidar && !services.lidar) blockers.push('Lidar driver is not running');
  if (!cameraDeviceAvailable) blockers.push('Camera device is missing');
  if (cameraDeviceAvailable && !cameraStreamAvailable) blockers.push('Camera stream is not running');
  if (!rosbridgeConnected) blockers.push('ROSBridge is not connected');
  if (runtime.navigation.safetyState !== 'READY') {
    blockers.push(`Safety state is ${runtime.navigation.safetyState}`);
  }

  runtime.status.canDrive = blockers.length === 0;
  runtime.status.blockers = blockers;
}

export function markEmergencyStop(reason) {
  runtime.safety.emergencyStopActive = true;
  runtime.safety.lastStopAt = new Date().toISOString();
  runtime.safety.lastStopReason = reason;
  runtime.command.active = false;
  runtime.command.lastTwist = null;
  runtime.command.heartbeat.connected = false;
  runtime.command.straightAssist = {
    ...inactiveStraightAssist(reason),
    updatedAt: new Date().toISOString()
  };
  bus.emit('snapshot', snapshot());
}

export function markCommandStopped(reason) {
  runtime.command.active = false;
  runtime.command.lastDriveAt = null;
  runtime.command.lastTwist = null;
  runtime.command.straightAssist = {
    ...inactiveStraightAssist(reason),
    updatedAt: new Date().toISOString()
  };
  bus.emit('snapshot', snapshot());
}

export function clearEmergencyStop() {
  runtime.safety.emergencyStopActive = false;
  bus.emit('snapshot', snapshot());
}

export function snapshot() {
  recomputeCanDrive();
  refreshRealtimeAges();
  const heartbeatAt = Date.parse(runtime.command.heartbeat.lastAt);
  runtime.command.heartbeat.ageMs = Number.isFinite(heartbeatAt) ? Math.max(0, Date.now() - heartbeatAt) : null;
  runtime.command.heartbeat.connected = runtime.command.heartbeat.protectionEnabled === false
    || (runtime.command.heartbeat.ageMs !== null
      && runtime.command.heartbeat.ageMs <= runtime.command.heartbeat.timeoutMs);
  return {
    runtime,
    telemetry
  };
}

function refreshRealtimeAges() {
  const now = Date.now();
  for (const value of Object.values(runtime.topicActivity)) {
    const updated = Date.parse(value.lastAt);
    value.ageMs = Number.isFinite(updated) ? Math.max(0, now - updated) : null;
    value.stale = value.ageMs === null || value.ageMs > 5000;
  }
  for (const key of [
    'lidar', 'imu', 'voltage', 'velocity', 'map', 'globalCostmap', 'localCostmap',
    'globalPath', 'localPath', 'patrolRoute', 'odometry', 'amclPose', 'tfPose', 'pose',
    'camera', 'depth', 'ir', 'pointCloud', 'tracking', 'detections'
  ]) {
    const value = telemetry[key];
    if (!value) continue;
    const updated = Date.parse(value.updatedAt);
    value.ageMs = Number.isFinite(updated) ? Math.max(0, now - updated) : null;
    value.stale = value.ageMs === null || value.ageMs > 5000;
    value.disconnectedReason = value.stale
      ? (value.ageMs === null ? '尚未收到真实数据' : '超过 5 秒未收到新数据，保留最后一次真实采样')
      : null;
  }
}
