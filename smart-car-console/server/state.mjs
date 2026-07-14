import { EventEmitter } from 'node:events';

export const bus = new EventEmitter();

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
    current: null,
    power: null,
    percent: null,
    updatedAt: null
  },
  accessoryPower: {
    connected: false,
    reason: 'No accessory-side battery telemetry source discovered',
    devices: [],
    updatedAt: null
  },
  encoders: {
    connected: false,
    leftTicks: null,
    rightTicks: null,
    deltaTicks: null,
    leftRadPerSec: null,
    rightRadPerSec: null,
    updatedAt: null
  },
  velocity: {
    connected: false,
    linear: null,
    angular: null,
    updatedAt: null
  },
  environment: {
    connected: false,
    reason: 'No Jetson-side data source discovered',
    temperature: null,
    humidity: null,
    pressure: null,
    airQuality: null,
    ambientLight: null,
    soundLevel: null,
    updatedAt: null
  }
};

export const runtime = {
  startedByConsole: false,
  rosbridge: {
    connected: false,
    url: null,
    lastError: null,
    updatedAt: null
  },
  command: {
    lastDriveAt: null,
    active: false,
    lastTwist: null
  },
  safety: {
    emergencyStopActive: false,
    lastStopAt: null,
    lastStopReason: null
  },
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
  bus.emit('snapshot', snapshot());
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

export function updateTelemetry(partial) {
  for (const [key, value] of Object.entries(partial)) {
    telemetry[key] = {
      ...telemetry[key],
      ...value,
      updatedAt: new Date().toISOString()
    };
  }
  bus.emit('snapshot', snapshot());
}

export function updateRosbridge(partial) {
  runtime.rosbridge = {
    ...runtime.rosbridge,
    ...partial,
    updatedAt: new Date().toISOString()
  };
  recomputeCanDrive();
  bus.emit('snapshot', snapshot());
}

export function recomputeCanDrive() {
  const blockers = [];
  const { devices, services } = runtime.status;
  const rosbridgeConnected = runtime.rosbridge.connected || runtime.status.ports.rosbridge9090;
  const cameraDeviceAvailable = devices.video0 || (devices.cameraDepth && devices.cameraUvc);
  const cameraStreamAvailable = runtime.status.ports.video6500 || services.video || services.camera;

  if (!devices.chassisSerial) blockers.push('Chassis serial device is missing');
  if (devices.chassisSerial && !services.chassis) blockers.push('Chassis driver is not running');
  if (!devices.lidar) blockers.push('RPLidar device is missing');
  if (devices.lidar && !services.lidar) blockers.push('Lidar driver is not running');
  if (!cameraDeviceAvailable) blockers.push('Camera device is missing');
  if (cameraDeviceAvailable && !cameraStreamAvailable) blockers.push('Camera stream is not running');
  if (!rosbridgeConnected) blockers.push('ROSBridge is not connected');

  runtime.status.canDrive = blockers.length === 0;
  runtime.status.blockers = blockers;
}

export function markEmergencyStop(reason) {
  runtime.safety.emergencyStopActive = true;
  runtime.safety.lastStopAt = new Date().toISOString();
  runtime.safety.lastStopReason = reason;
  runtime.command.active = false;
  runtime.command.lastTwist = null;
  bus.emit('snapshot', snapshot());
}

export function clearEmergencyStop() {
  runtime.safety.emergencyStopActive = false;
  bus.emit('snapshot', snapshot());
}

export function snapshot() {
  recomputeCanDrive();
  return {
    runtime,
    telemetry
  };
}
