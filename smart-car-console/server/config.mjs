import { readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const rootDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const configPath = path.join(rootDir, 'local-config.json');
const examplePath = path.join(rootDir, 'local-config.example.json');

const defaults = {
  car: {
    host: '192.168.43.137',
    sshUser: 'jetson',
    sshPassword: '',
    sshHostKey: 'SHA256:AJffjk3YWwStux7ZbdKdft3teC8b7Jsubuvv4zMYuD8',
    plinkPath: 'D:\\putty\\plink.exe'
  },
  control: {
    maxLinearMps: 0.05,
    maxAngularRps: 0.2,
    turnScale: -1,
    deadZone: 0.05,
    watchdogMs: 500,
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
  },
  navigation: {
    enabled: true,
    mode: 'safe_base',
    overlaySetup: '/root/ros2_navigation_overlay/install/setup.bash',
    map: '/root/ros2_navigation_overlay/install/share/icar_navigation/maps/campus_map.yaml',
    routeFile: '/root/ros2_navigation_overlay/install/share/icar_navigation/config/patrol_route.yaml',
    maxLinearMps: 0.05,
    maxAngularRps: 0.2,
    autoStartPatrol: false
  },
  safety: {
    motionWarningAcknowledgedAt: null
  }
};

const controlSafetyCeiling = {
  maxLinearMps: 0.1,
  maxAngularRps: 0.4,
  watchdogMs: 500
};

let activeConfig = structuredClone(defaults);

export function parseConfigText(text) {
  return JSON.parse(String(text).replace(/^\uFEFF/, ''));
}

function clampNumber(value, min, max, fallback) {
  const number = Number(value);
  if (!Number.isFinite(number)) return fallback;
  return Math.min(max, Math.max(min, number));
}

function normalizeControlConfig(control = {}) {
  const merged = {
    ...defaults.control,
    ...control,
    straightAssist: {
      ...defaults.control.straightAssist,
      ...(control?.straightAssist ?? {})
    }
  };
  return {
    ...merged,
    maxLinearMps: clampNumber(merged.maxLinearMps, 0.01, controlSafetyCeiling.maxLinearMps, defaults.control.maxLinearMps),
    maxAngularRps: clampNumber(merged.maxAngularRps, 0.05, controlSafetyCeiling.maxAngularRps, defaults.control.maxAngularRps),
    deadZone: clampNumber(merged.deadZone, 0, 0.5, defaults.control.deadZone),
    watchdogMs: controlSafetyCeiling.watchdogMs,
    heartbeatProtectionEnabled: merged.heartbeatProtectionEnabled !== false,
    straightAssist: {
      ...merged.straightAssist,
      gain: clampNumber(merged.straightAssist.gain, 0, 2, defaults.control.straightAssist.gain),
      maxCorrectionRps: clampNumber(
        merged.straightAssist.maxCorrectionRps,
        0,
        defaults.control.straightAssist.maxCorrectionRps,
        defaults.control.straightAssist.maxCorrectionRps
      )
    }
  };
}

function mergeConfig(config) {
  const requestedMode = String(config?.navigation?.mode ?? defaults.navigation.mode);
  const navigationMode = ['safe_base', 'mapping', 'navigation', 'demo'].includes(requestedMode)
    ? requestedMode
    : defaults.navigation.mode;
  return {
    car: {
      ...defaults.car,
      ...(config?.car ?? {})
    },
    control: normalizeControlConfig(config?.control),
    video: {
      ...defaults.video,
      ...(config?.video ?? {})
    },
    navigation: {
      ...defaults.navigation,
      ...(config?.navigation ?? {}),
      enabled: config?.navigation?.enabled !== false,
      mode: navigationMode,
      maxLinearMps: clampNumber(
        config?.navigation?.maxLinearMps,
        0.05,
        controlSafetyCeiling.maxLinearMps,
        defaults.navigation.maxLinearMps
      ),
      maxAngularRps: clampNumber(
        config?.navigation?.maxAngularRps,
        0.2,
        controlSafetyCeiling.maxAngularRps,
        defaults.navigation.maxAngularRps
      ),
      autoStartPatrol: false
    },
    safety: {
      motionWarningAcknowledgedAt: typeof config?.safety?.motionWarningAcknowledgedAt === 'string'
        ? config.safety.motionWarningAcknowledgedAt
        : null
    }
  };
}

export async function loadConfig() {
  try {
    const text = await readFile(configPath, 'utf8');
    activeConfig = mergeConfig(parseConfigText(text));
    return activeConfig;
  } catch {
    try {
      const text = await readFile(examplePath, 'utf8');
      activeConfig = mergeConfig(parseConfigText(text));
      return activeConfig;
    } catch {
      activeConfig = structuredClone(defaults);
      return activeConfig;
    }
  }
}

export function getConfig() {
  return activeConfig;
}

export function publicConfig() {
  const config = getConfig();
  return {
    car: {
      host: config.car.host,
      sshUser: config.car.sshUser,
      sshPasswordSet: Boolean(config.car.sshPassword),
      sshHostKeySet: Boolean(config.car.sshHostKey),
      plinkConfigured: Boolean(config.car.plinkPath)
    },
    control: config.control,
    video: config.video,
    navigation: config.navigation,
    safety: {
      motionWarningAcknowledged: Boolean(config.safety?.motionWarningAcknowledgedAt),
      motionWarningAcknowledgedAt: config.safety?.motionWarningAcknowledgedAt ?? null
    }
  };
}

export function mergeApiConfig(current, body = {}) {
  const requestedCar = body?.car && typeof body.car === 'object' ? body.car : {};
  const host = String(requestedCar.host ?? current.car.host).trim();
  const sshUser = String(requestedCar.sshUser ?? current.car.sshUser).trim();
  if (!/^[A-Za-z0-9.-]{1,253}$/.test(host)) throw invalidApiConfig('Invalid car host');
  if (!/^[A-Za-z0-9._-]{1,64}$/.test(sshUser)) throw invalidApiConfig('Invalid SSH user');
  const requestedPassword = typeof requestedCar.sshPassword === 'string' ? requestedCar.sshPassword : '';
  if (requestedPassword.length > 512) throw invalidApiConfig('SSH password is too long');
  return {
    car: {
      ...current.car,
      host,
      sshUser,
      sshPassword: requestedPassword || current.car.sshPassword
    },
    control: { ...current.control, ...(body?.control ?? {}) },
    video: { ...current.video, ...(body?.video ?? {}) },
    navigation: { ...current.navigation, ...(body?.navigation ?? {}) },
    safety: { ...current.safety }
  };
}

function invalidApiConfig(message) {
  const error = new Error(message);
  error.statusCode = 400;
  return error;
}

export async function saveConfig(nextConfig) {
  activeConfig = mergeConfig(nextConfig);
  await writeFile(configPath, `${JSON.stringify(activeConfig, null, 2)}\n`, 'utf8');
  return activeConfig;
}
