import { readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const rootDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const configPath = path.join(rootDir, 'local-config.json');
const examplePath = path.join(rootDir, 'local-config.example.json');

const defaults = {
  car: {
    host: process.env.SMART_CAR_HOST || '',
    sshUser: 'jetson',
    sshPassword: '',
    sshHostKey: '',
    plinkPath: 'C:\\Program Files\\PuTTY\\plink.exe',
    sshPrivateKey: ''
  },
  control: {
    maxLinearMps: 0.5,
    maxAngularRps: 2,
    turnScale: -1,
    deadZone: 0.05,
    watchdogMs: 500,
    commandTopic: '/cmd_vel_manual',
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
    maxLinearMps: 0.5,
    maxAngularRps: 2,
    autoStartPatrol: false
  },
  safety: {
    motionWarningAcknowledgedAt: null
  },
  agent: {
    host: '',
    port: 8100,
    token: '',
    requestTimeoutMs: 20000
  }
};

const controlSafetyCeiling = {
  maxLinearMps: 0.5,
  maxAngularRps: 2,
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
    commandTopic: '/cmd_vel_manual',
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
      ...(config?.car ?? {}),
      host: process.env.SMART_CAR_HOST || config?.car?.host || defaults.car.host,
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
    },
    agent: {
      ...defaults.agent,
      ...(config?.agent ?? {})
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
      plinkConfigured: Boolean(config.car.plinkPath),
      sshPrivateKeySet: Boolean(config.car.sshPrivateKey)
    },
    control: config.control,
    video: config.video,
    navigation: config.navigation,
    safety: {
      motionWarningAcknowledged: Boolean(config.safety?.motionWarningAcknowledgedAt),
      motionWarningAcknowledgedAt: config.safety?.motionWarningAcknowledgedAt ?? null
    },
    agent: {
      host: config.agent.host,
      port: config.agent.port,
      tokenSet: Boolean(config.agent.token),
      requestTimeoutMs: config.agent.requestTimeoutMs
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
  const requestedAgent = body?.agent && typeof body.agent === 'object' ? body.agent : {};
  const agentHost = String(requestedAgent.host ?? current.agent?.host ?? '').trim();
  if (agentHost && !/^[A-Za-z0-9.-]{1,253}$/.test(agentHost)) {
    throw invalidApiConfig('Invalid agent host');
  }
  const agentPort = clampNumber(requestedAgent.port, 1, 65535, current.agent?.port ?? defaults.agent.port);
  const requestTimeoutMs = clampNumber(
    requestedAgent.requestTimeoutMs,
    1000,
    120000,
    current.agent?.requestTimeoutMs ?? defaults.agent.requestTimeoutMs
  );
  const requestedToken = typeof requestedAgent.token === 'string' ? requestedAgent.token : '';
  if (requestedToken.length > 4096) throw invalidApiConfig('Agent token is too long');
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
    safety: { ...current.safety },
    agent: {
      ...current.agent,
      host: agentHost,
      port: agentPort,
      token: requestedToken || current.agent?.token || '',
      requestTimeoutMs
    }
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
