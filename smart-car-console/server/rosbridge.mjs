import { EventEmitter } from 'node:events';
import WebSocket from 'ws';
import { ZERO_TWIST } from './control.mjs';
import { addLog, updateRosbridge, updateTelemetry } from './state.mjs';

const subscriptions = [
  { topic: '/scan', type: 'sensor_msgs/LaserScan' },
  { topic: '/imu/data_raw', type: 'sensor_msgs/Imu' },
  { topic: '/imu/mag', type: 'sensor_msgs/MagneticField' },
  { topic: '/voltage', type: 'std_msgs/Float32' },
  { topic: '/vel_raw', type: 'geometry_msgs/Twist' },
  { topic: '/joint_states', type: 'sensor_msgs/JointState' }
];

export class RosbridgeClient extends EventEmitter {
  constructor(getConfig) {
    super();
    this.getConfig = getConfig;
    this.ws = null;
    this.connected = false;
    this.reconnectTimer = null;
    this.manualClose = false;
  }

  get url() {
    return `ws://${this.getConfig().car.host}:9090`;
  }

  connect() {
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
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
      for (const sub of subscriptions) this.subscribe(sub);
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
    this.ws?.close();
  }

  subscribe({ topic, type }) {
    this.send({
      op: 'subscribe',
      topic,
      type,
      throttle_rate: topic === '/scan' ? 120 : 200,
      queue_length: 1
    });
  }

  publish(topic, type, msg) {
    return this.send({ op: 'publish', topic, type, msg });
  }

  publishTwist(twist) {
    return this.publish('/cmd_vel', 'geometry_msgs/Twist', twist);
  }

  emergencyStop(repeat = 4) {
    let sent = 0;
    const sendZero = () => {
      if (this.connected) {
        this.publishTwist(ZERO_TWIST);
        sent += 1;
      }
    };
    sendZero();
    for (let index = 1; index < repeat; index += 1) {
      setTimeout(sendZero, index * 80);
    }
    return sent > 0;
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
    if (payload.op !== 'publish' || !payload.topic) return;
    const msg = payload.msg ?? {};
    if (payload.topic === '/scan') updateTelemetry({ lidar: parseScan(msg) });
    if (payload.topic === '/imu/data_raw') updateTelemetry({ imu: parseImu(msg) });
    if (payload.topic === '/imu/mag') updateTelemetry({ imu: parseMag(msg) });
    if (payload.topic === '/voltage') updateTelemetry({ voltage: parseVoltage(msg) });
    if (payload.topic === '/vel_raw') updateTelemetry({ velocity: parseVelocity(msg) });
    if (payload.topic === '/joint_states') updateTelemetry({ encoders: parseJointStates(msg) });
  }
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
  const battery = round(msg.data ?? msg.voltage ?? msg.value, 2);
  return {
    connected: battery !== null,
    battery,
    current: round(msg.current, 2),
    power: round(battery !== null && msg.current !== undefined ? battery * finite(msg.current, 0) : msg.power, 2),
    percent: estimateBatteryPercent(battery)
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

function parseJointStates(msg) {
  const positions = Array.isArray(msg.position) ? msg.position : [];
  const velocities = Array.isArray(msg.velocity) ? msg.velocity : [];
  const left = finite(positions[0]);
  const right = finite(positions[1]);
  return {
    connected: positions.length > 0 || velocities.length > 0,
    leftTicks: left === null ? null : Math.round(left * 1000),
    rightTicks: right === null ? null : Math.round(right * 1000),
    deltaTicks: left === null || right === null ? null : Math.round((right - left) * 1000),
    leftRadPerSec: round(velocities[0], 3),
    rightRadPerSec: round(velocities[1], 3)
  };
}
