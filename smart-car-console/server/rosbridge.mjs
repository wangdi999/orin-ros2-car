import { EventEmitter } from 'node:events';
import WebSocket from 'ws';
import { ZERO_TWIST } from './control.mjs';
import { parseDetectionsMessage } from './detectionParser.mjs';
import { parseCompressedImage, parseImagePreview } from './imagePreview.mjs';
import {
  Tf2dBuffer,
  parseOccupancyGrid,
  parseOdometry,
  parsePath,
  parsePoseWithCovariance,
  resolveMapPose
} from './mapTelemetry.mjs';
import { parsePointCloud2 } from './pointCloud.mjs';
import {
  addLog,
  clearMappingTelemetry,
  clearPerceptionTelemetry,
  telemetry,
  updateNavigation,
  updateRosbridge,
  updateTelemetry,
  updateTopicActivity
} from './state.mjs';
import { rosbridgeType } from './topicDiscovery.mjs';
import { subscriptionTopics } from './topicRegistry.mjs';
import {
  INITIAL_POSE_TOPIC,
  INITIAL_POSE_TYPE,
  NAVIGATE_POSE_SERVICE,
  NAVIGATE_POSE_SERVICE_TYPE,
  buildInitialPoseMessage,
  normalizePose
} from './navigationProtocol.mjs';

export const ROS2_TWIST_TYPE = 'geometry_msgs/msg/Twist';
export const ROS2_BOOL_TYPE = 'std_msgs/msg/Bool';
export const MANUAL_CMD_TOPIC = '/cmd_vel_manual';
export const ESTOP_TOPIC = '/safety/estop';
export const TRIGGER_SERVICE_TYPE = 'std_srvs/srv/Trigger';

export class RosbridgeClient extends EventEmitter {
  constructor(getConfig) {
    super();
    this.getConfig = getConfig;
    this.ws = null;
    this.connected = false;
    this.reconnectTimer = null;
    this.manualClose = false;
    this.serviceSequence = 0;
    this.pendingServiceCalls = new Map();
    this.tfBuffer = new Tf2dBuffer();
    this.amclPose = null;
    this.odomPose = null;
    this.perceptionSubscriptions = new Map();
    this.activePerceptionSubscriptions = new Map();
    this.perceptionPreviewEnabled = false;
  }

  get url() {
    return `ws://${this.getConfig().car.host}:9090`;
  }

  connect() {
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
      return;
    }
    const host = String(this.getConfig()?.car?.host || '').trim();
    if (!host) {
      updateRosbridge({ connected: false, url: null, lastError: 'Car host is not configured' });
      addLog('warn', 'rosbridge', 'Car host is not configured; ROSBridge connection is disabled');
      return;
    }
    this.manualClose = false;
    updateRosbridge({ url: this.url, lastError: null });
    const ws = new WebSocket(this.url, { handshakeTimeout: 2500 });
    this.ws = ws;

    ws.on('open', () => {
      this.connected = true;
      updateRosbridge({ connected: true, url: this.url, lastError: null });
      addLog('info', 'rosbridge', `Connected to ${this.url}`);
      this.advertise(MANUAL_CMD_TOPIC, ROS2_TWIST_TYPE, 1);
      this.advertise(ESTOP_TOPIC, ROS2_BOOL_TYPE, 1);
      this.advertise(INITIAL_POSE_TOPIC, INITIAL_POSE_TYPE, 1);
      for (const sub of subscriptionTopics()) this.subscribe(sub);
      this.activePerceptionSubscriptions.clear();
      this.syncPerceptionSubscriptions();
    });

    ws.on('message', (data) => {
      this.handleMessage(data.toString('utf8'));
    });

    ws.on('error', (error) => {
      updateRosbridge({ connected: false, url: this.url, lastError: error.message });
    });

    ws.on('close', () => {
      const wasConnected = this.connected;
      this.connected = false;
      this.resetLocalizationBuffers();
      this.failPendingServiceCalls('ROSBridge connection closed');
      updateRosbridge({ connected: false, url: this.url });
      if (wasConnected) {
        addLog('warn', 'rosbridge', 'Connection closed; requesting stop fallback');
        this.emit('disconnect');
      }
      if (!this.manualClose) this.scheduleReconnect();
    });
  }

  scheduleReconnect() {
    if (this.reconnectTimer) return;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, 2500);
  }

  close() {
    this.manualClose = true;
    clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
    this.resetLocalizationBuffers();
    this.ws?.close();
  }

  resetLocalizationBuffers() {
    this.tfBuffer.clear();
    this.amclPose = null;
    this.odomPose = null;
  }

  resetMappingSession() {
    this.resetLocalizationBuffers();
    clearMappingTelemetry();
  }

  subscribe({ topic, type, throttleRate, queueLength }) {
    if (!topic || !type) return;
    this.send({
      op: 'subscribe',
      topic,
      type,
      throttle_rate: throttleRate ?? (topic === '/scan' ? 120 : 200),
      queue_length: queueLength ?? 1
    });
  }

  unsubscribe(topic) {
    if (!topic) return false;
    return this.send({ op: 'unsubscribe', topic });
  }

  advertise(topic, type, queueSize = 1) {
    return this.send({
      op: 'advertise',
      topic,
      type,
      queue_size: queueSize
    });
  }

  setPerceptionSubscriptions(matches = {}) {
    const next = new Map();
    for (const match of Object.values(matches)) {
      if (!match?.topic || !match?.type) continue;
      const type = rosbridgeType(match.type);
      if (!type) continue;
      next.set(match.topic, {
        role: match.role,
        type,
        throttleRate: perceptionThrottleRate(match.role),
        queueLength: 1
      });
    }
    this.perceptionSubscriptions = next;
    this.syncPerceptionSubscriptions();
  }

  setPerceptionPreviewEnabled(enabled) {
    this.perceptionPreviewEnabled = Boolean(enabled);
    this.syncPerceptionSubscriptions();
    if (!this.perceptionPreviewEnabled) clearPerceptionTelemetry();
  }

  syncPerceptionSubscriptions() {
    if (!this.connected) return;
    const desired = this.perceptionPreviewEnabled ? this.perceptionSubscriptions : new Map();
    for (const topic of this.activePerceptionSubscriptions.keys()) {
      if (!desired.has(topic)) {
        this.unsubscribe(topic);
        this.activePerceptionSubscriptions.delete(topic);
      }
    }
    for (const [topic, value] of desired.entries()) {
      const active = this.activePerceptionSubscriptions.get(topic);
      if (sameSubscription(active, value)) continue;
      if (active) this.unsubscribe(topic);
      this.subscribe({ topic, ...value });
      this.activePerceptionSubscriptions.set(topic, value);
    }
  }

  publish(topic, msg) {
    return this.send({ op: 'publish', topic, msg });
  }

  publishTwist(twist) {
    return this.publish(MANUAL_CMD_TOPIC, twist);
  }

  publishInitialPose(pose) {
    return this.publish(INITIAL_POSE_TOPIC, buildInitialPoseMessage(pose));
  }

  sendNavigationGoal(pose, timeoutMs = 10000) {
    const goal = normalizePose(pose, 'goal');
    return this.callService(
      NAVIGATE_POSE_SERVICE,
      NAVIGATE_POSE_SERVICE_TYPE,
      goal,
      timeoutMs
    );
  }

  stopManual(repeat = 4) {
    let sent = 0;
    const sendZero = () => {
      if (this.connected) {
        if (this.publishTwist(ZERO_TWIST)) sent += 1;
      }
    };
    sendZero();
    for (let index = 1; index < repeat; index += 1) {
      setTimeout(sendZero, index * 80);
    }
    return sent > 0;
  }

  emergencyStop(repeat = 4) {
    const estopSent = this.publish(ESTOP_TOPIC, { data: true });
    const zeroSent = this.stopManual(repeat);
    return estopSent || zeroSent;
  }

  async resetSafety() {
    if (!this.publish(ESTOP_TOPIC, { data: false })) {
      return this.recordServiceResult('/safety/reset', {
        ok: false,
        success: false,
        message: 'ROSBridge is not connected'
      });
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
    return this.callTrigger('/safety/reset');
  }

  callTrigger(service, timeoutMs = 8000) {
    return this.callService(service, TRIGGER_SERVICE_TYPE, {}, timeoutMs);
  }

  callService(service, type, args = {}, timeoutMs = 8000) {
    if (!this.connected) {
      return Promise.resolve(this.recordServiceResult(service, {
        ok: false,
        success: false,
        message: 'ROSBridge is not connected'
      }));
    }
    const id = `service-${Date.now()}-${this.serviceSequence += 1}`;
    return new Promise((resolve) => {
      const timer = setTimeout(() => {
        this.pendingServiceCalls.delete(id);
        resolve(this.recordServiceResult(service, {
          ok: false,
          success: false,
          message: `${service} timed out after ${timeoutMs} ms`
        }));
      }, timeoutMs);
      this.pendingServiceCalls.set(id, { service, resolve, timer });
      if (!this.send({
        op: 'call_service',
        id,
        service,
        type,
        args
      })) {
        clearTimeout(timer);
        this.pendingServiceCalls.delete(id);
        resolve(this.recordServiceResult(service, {
          ok: false,
          success: false,
          message: 'ROSBridge is not connected'
        }));
      }
    });
  }

  failPendingServiceCalls(message) {
    for (const pending of this.pendingServiceCalls.values()) {
      clearTimeout(pending.timer);
      pending.resolve(this.recordServiceResult(
        pending.service, { ok: false, success: false, message }
      ));
    }
    this.pendingServiceCalls.clear();
  }

  send(message) {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return false;
    this.ws.send(JSON.stringify(message));
    return true;
  }

  handleMessage(text) {
    let payload;
    try {
      payload = JSON.parse(text);
    } catch {
      return;
    }
    if (payload.op === 'service_response' && payload.id) {
      this.handleServiceResponse(payload);
      return;
    }
    if (payload.op !== 'publish' || !payload.topic) return;
    const msg = payload.msg ?? {};
    const receivedAt = new Date().toISOString();
    updateTopicActivity(payload.topic, receivedAt);
    if (payload.topic === '/scan') updateTelemetry({ lidar: parseScan(msg) });
    if (payload.topic === '/imu/data_raw') updateTelemetry({ imu: parseImu(msg) });
    if (payload.topic === '/imu/mag') updateTelemetry({ imu: parseMag(msg) });
    if (payload.topic === '/voltage') updateTelemetry({ voltage: parseVoltage(msg) });
    if (payload.topic === '/vel_raw') updateTelemetry({ velocity: parseVelocity(msg) });
    if (payload.topic === '/map') updateTelemetry({ map: parseOccupancyGrid(msg) });
    if (payload.topic === '/global_costmap/costmap') updateTelemetry({ globalCostmap: parseOccupancyGrid(msg) });
    if (payload.topic === '/local_costmap/costmap') updateTelemetry({ localCostmap: parseOccupancyGrid(msg) });
    if (payload.topic === '/plan') updateTelemetry({ globalPath: parsePath(msg) });
    if (payload.topic === '/local_plan') updateTelemetry({ localPath: parsePath(msg) });
    if (payload.topic === '/patrol/route') updateTelemetry({ patrolRoute: parsePath(msg) });
    if (payload.topic === '/odom') {
      this.odomPose = { ...parseOdometry(msg), source: 'odom', updatedAt: receivedAt };
      this.refreshGlobalPose(receivedAt, { odometry: this.odomPose });
    }
    if (payload.topic === '/amcl_pose') {
      this.amclPose = { ...parsePoseWithCovariance(msg), updatedAt: receivedAt };
      this.refreshGlobalPose(receivedAt, { amclPose: this.amclPose });
    }
    if (payload.topic === '/tf' || payload.topic === '/tf_static') {
      this.tfBuffer.update(msg, receivedAt, payload.topic === '/tf_static');
      this.refreshGlobalPose(receivedAt);
    }
    if (payload.topic === '/control/active_source') {
      updateNavigation({ activeSource: String(msg.data ?? 'UNKNOWN') });
    }
    if (payload.topic === '/safety/state') {
      updateNavigation({ safetyState: String(msg.data ?? 'UNKNOWN') });
    }
    if (payload.topic === '/chassis/connected') {
      updateNavigation({ chassisConnected: Boolean(msg.data) });
    }
    if (payload.topic === '/patrol/status') {
      updateNavigation({ patrol: parsePatrolStatus(msg) });
    }
    if (payload.topic === '/navigation/status') {
      updateNavigation({ goal: parsePatrolStatus(msg) });
    }
    if (payload.topic === '/navigate_to_pose/_action/status') {
      updateNavigation({ action: parseNavigateStatus(msg, receivedAt) });
    }
    if (payload.topic === '/alarm') this.emit('car-alarm', parseTypedAlarm(msg));
    if (payload.topic === '/alarm_events') this.emit('car-alarm', parseAlarmEvent(msg));
    const perception = this.perceptionPreviewEnabled && this.perceptionSubscriptions.get(payload.topic);
    if (perception) this.handlePerceptionMessage(payload.topic, perception, msg);
  }

  refreshGlobalPose(now, partial = {}) {
    const tfPose = this.tfBuffer.resolve('map', 'base_footprint');
    const resolved = resolveMapPose({ amcl: this.amclPose, tfPose, odom: this.odomPose }, now);
    const previous = telemetry.pose;
    const hasPreviousPose = previous?.pose?.x !== null && previous?.pose?.y !== null;
    const pose = !resolved.connected && hasPreviousPose
      ? {
          ...previous,
          connected: false,
          stale: true,
          disconnectedReason: resolved.reason,
          reason: resolved.reason
        }
      : resolved;
    updateTelemetry({ ...partial, tfPose, pose });
  }

  handleServiceResponse(payload) {
    const pending = this.pendingServiceCalls.get(payload.id);
    if (!pending) return;
    this.pendingServiceCalls.delete(payload.id);
    clearTimeout(pending.timer);
    const rawValues = payload.values;
    const values = rawValues && typeof rawValues === 'object' && !Array.isArray(rawValues)
      ? rawValues
      : {};
    const transportOk = payload.result !== false;
    const serviceAccepted = values.accepted !== false && values.success !== false;
    const success = transportOk && serviceAccepted;
    const transportMessage = typeof rawValues === 'string' ? rawValues : payload.message;
    const result = this.recordServiceResult(pending.service, {
      ok: transportOk,
      success,
      message: String(values.message ?? transportMessage ?? (success ? 'accepted' : 'rejected')),
      values
    });
    pending.resolve(result);
  }

  recordServiceResult(service, result) {
    const completed = {
      ...result,
      service,
      completedAt: new Date().toISOString()
    };
    updateNavigation({ lastService: completed });
    return completed;
  }

  handlePerceptionMessage(topic, perception, msg) {
    if (perception.role === 'camera') {
      updateTelemetry({ camera: { ...parseVisualMessage(msg, 'camera', perception.type), topic, type: perception.type } });
    }
    if (perception.role === 'depth') {
      updateTelemetry({ depth: { ...parseVisualMessage(msg, 'depth', perception.type), topic, type: perception.type } });
    }
    if (perception.role === 'ir') {
      updateTelemetry({ ir: { ...parseVisualMessage(msg, 'ir', perception.type), topic, type: perception.type } });
    }
    if (perception.role === 'pointCloud') {
      updateTelemetry({ pointCloud: { ...parsePointCloud2(msg), topic, type: perception.type } });
    }
    if (perception.role === 'trackingImage') {
      updateTelemetry({
        tracking: {
          connected: true,
          imageTopic: topic,
          image: { ...parseVisualMessage(msg, 'tracking', perception.type), topic, type: perception.type }
        }
      });
    }
    if (perception.role === 'trackingVelocity') {
      updateTelemetry({
        tracking: {
          connected: true,
          velocityTopic: topic,
          shadowTwist: parseTrackingTwist(msg)
        }
      });
    }
    if (perception.role === 'detections') {
      updateTelemetry({
        detections: {
          ...parseDetectionsMessage(msg, perception.type),
          topic,
          type: perception.type
        }
      });
    }
  }
}

function parseVisualMessage(msg, role, type) {
  if (type?.includes('CompressedImage')) return parseCompressedImage(msg);
  return parseImagePreview(msg, role);
}

function parseAlarmEvent(msg = {}) {
  const data = msg.data ?? msg;
  if (typeof data !== 'string') {
    return data?.code ? parseTypedAlarm(data) : data;
  }
  try {
    const parsed = JSON.parse(data);
    return parsed?.code ? parseTypedAlarm(parsed) : parsed;
  } catch {
    return data;
  }
}

function parseTypedAlarm(msg = {}) {
  const severity = Number(msg.severity);
  const severityName = ['info', 'warning', 'error', 'critical'][severity] ?? 'warning';
  const code = String(msg.code ?? 'car_alarm');
  return {
    source: String(msg.source ?? 'car'),
    type: code,
    severity: severityName,
    title: code,
    message: String(msg.message ?? code),
    state: String(msg.state ?? ''),
    active: msg.active !== false,
    dedupeKey: `${String(msg.source ?? 'car')}:${code}`,
    header: msg.header ?? null
  };
}

function parsePatrolStatus(msg = {}) {
  const data = msg.data ?? msg;
  let parsed = data;
  if (typeof data === 'string') {
    try {
      parsed = JSON.parse(data);
    } catch {
      return {
        state: 'INVALID',
        reason: 'patrol status is not valid JSON'
      };
    }
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    return { state: 'INVALID', reason: 'patrol status is not an object' };
  }
  return {
    state: String(parsed.state ?? 'UNKNOWN'),
    mode: parsed.mode == null ? null : String(parsed.mode),
    waypoint: parsed.waypoint == null ? null : String(parsed.waypoint),
    index: finite(parsed.index),
    attempt: finite(parsed.attempt),
    routeConfigured: Boolean(parsed.route_configured),
    reason: parsed.reason == null ? null : String(parsed.reason),
    goalId: parsed.goal_id == null ? null : String(parsed.goal_id)
  };
}

function finite(value, fallback = null) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function round(value, places = 3) {
  const number = finite(value);
  if (number === null) return null;
  const scale = 10 ** places;
  return Math.round(number * scale) / scale;
}

function parseScan(msg) {
  const angleMin = finite(msg.angle_min, 0);
  const angleIncrement = finite(msg.angle_increment, 0);
  const rangeMax = finite(msg.range_max, 12);
  const ranges = Array.isArray(msg.ranges) ? msg.ranges : [];
  const step = Math.max(1, Math.floor(ranges.length / 720));
  const points = [];
  for (let index = 0; index < ranges.length; index += step) {
    const range = finite(ranges[index]);
    if (range === null || range <= 0.02 || range > rangeMax) continue;
    points.push({
      angle: round(angleMin + angleIncrement * index, 4),
      range: round(range, 3)
    });
  }
  return {
    connected: true,
    frameId: msg.header?.frame_id ?? null,
    rangeMax: round(rangeMax, 1) ?? 12,
    points
  };
}

function quaternionToEuler(q = {}) {
  const x = finite(q.x, 0);
  const y = finite(q.y, 0);
  const z = finite(q.z, 0);
  const w = finite(q.w, 1);
  const norm = Math.sqrt(x * x + y * y + z * z + w * w);
  if (!Number.isFinite(norm) || norm < 0.001) {
    return { roll: null, pitch: null, yaw: null };
  }
  const sinr = 2 * (w * x + y * z);
  const cosr = 1 - 2 * (x * x + y * y);
  const roll = Math.atan2(sinr, cosr);
  const sinp = 2 * (w * y - z * x);
  const pitch = Math.abs(sinp) >= 1 ? Math.sign(sinp) * Math.PI / 2 : Math.asin(sinp);
  const siny = 2 * (w * z + x * y);
  const cosy = 1 - 2 * (y * y + z * z);
  const yaw = Math.atan2(siny, cosy);
  return {
    roll: round(roll * 180 / Math.PI, 2),
    pitch: round(pitch * 180 / Math.PI, 2),
    yaw: round(yaw * 180 / Math.PI, 2)
  };
}

function parseImu(msg) {
  return {
    connected: true,
    orientation: quaternionToEuler(msg.orientation),
    acceleration: {
      x: round(msg.linear_acceleration?.x, 3),
      y: round(msg.linear_acceleration?.y, 3),
      z: round(msg.linear_acceleration?.z, 3)
    },
    gyro: {
      x: round(msg.angular_velocity?.x, 3),
      y: round(msg.angular_velocity?.y, 3),
      z: round(msg.angular_velocity?.z, 3)
    }
  };
}

function parseMag(msg) {
  const field = msg.magnetic_field ?? {};
  return {
    connected: true,
    magnetometer: {
      x: round(finite(field.x, 0) * 1_000_000, 2),
      y: round(finite(field.y, 0) * 1_000_000, 2),
      z: round(finite(field.z, 0) * 1_000_000, 2)
    }
  };
}

function parseVoltage(msg) {
  const rawBattery = round(msg.data ?? msg.voltage ?? msg.value, 2);
  const battery = rawBattery !== null && rawBattery >= 1 ? rawBattery : null;
  const invalidReason = rawBattery !== null && rawBattery < 1
    ? `Ignoring invalid /voltage sample ${rawBattery} V`
    : null;
  return {
    connected: battery !== null,
    rawBattery,
    battery,
    percent: estimateBatteryPercent(battery),
    percentEstimated: true,
    invalidReason
  };
}

function estimateBatteryPercent(voltage) {
  const battery = finite(voltage);
  if (battery === null) return null;
  const emptyVoltage = 9.6;
  const fullVoltage = 12.6;
  return Math.max(0, Math.min(100, Math.round((battery - emptyVoltage) / (fullVoltage - emptyVoltage) * 100)));
}

function parseVelocity(msg) {
  return {
    connected: true,
    linear: round(msg.linear?.x ?? msg.x ?? msg.data?.[0], 3),
    angular: round(msg.angular?.z ?? msg.z ?? msg.data?.[1], 3)
  };
}

function parseTrackingTwist(msg) {
  return {
    linear: {
      x: round(msg.linear?.x, 3),
      y: round(msg.linear?.y, 3),
      z: round(msg.linear?.z, 3)
    },
    angular: {
      x: round(msg.angular?.x, 3),
      y: round(msg.angular?.y, 3),
      z: round(msg.angular?.z, 3)
    }
  };
}

function perceptionThrottleRate(role) {
  return role === 'pointCloud' ? 500 : 200;
}

function sameSubscription(previous, next) {
  return previous?.role === next?.role
    && previous?.type === next?.type
    && previous?.throttleRate === next?.throttleRate
    && previous?.queueLength === next?.queueLength;
}

function parseNavigateStatus(msg = {}, updatedAt = new Date().toISOString()) {
  const statuses = Array.isArray(msg.status_list) ? msg.status_list : [];
  const active = statuses.filter((entry) => [1, 2, 3].includes(Number(entry.status)));
  const latest = statuses.at(-1);
  const names = {
    0: 'UNKNOWN', 1: 'ACCEPTED', 2: 'EXECUTING', 3: 'CANCELING',
    4: 'SUCCEEDED', 5: 'CANCELED', 6: 'ABORTED'
  };
  return {
    status: names[Number(latest?.status)] ?? 'UNKNOWN',
    activeGoals: active.length,
    updatedAt
  };
}
