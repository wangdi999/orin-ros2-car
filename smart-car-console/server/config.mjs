import { readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const rootDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const configPath = path.join(rootDir, 'local-config.json');
const examplePath = path.join(rootDir, 'local-config.example.json');

const defaults = {
  car: {
    host: process.env.SMART_CAR_HOST || '192.168.160.196',
    sshUser: 'jetson',
    sshPassword: 'yahboom',
    sshHostKey: 'SHA256:AJffjk3YWwStux7ZbdKdft3teC8b7Jsubuvv4zMYuD8',
    plinkPath: 'C:\\Program Files\\PuTTY\\plink.exe',
    sshPrivateKey: ''
  },
  control: {
    maxLinearMps: 0.10,
    maxAngularRps: 0.20,
    deadZone: 0.05,
    watchdogMs: 450,
    commandTopic: '/cmd_vel_manual'
  },
  agent: {
    host: '',
    port: 8100,
    token: '',
    requestTimeoutMs: 20000
  }
};

let activeConfig = structuredClone(defaults);

function mergeConfig(config) {
  return {
    car: {
      ...defaults.car,
      ...(config?.car ?? {}),
      host: process.env.SMART_CAR_HOST || config?.car?.host || defaults.car.host,
    },
    control: {
      ...defaults.control,
      ...(config?.control ?? {})
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
    activeConfig = mergeConfig(JSON.parse(text));
    return activeConfig;
  } catch {
    try {
      const text = await readFile(examplePath, 'utf8');
      activeConfig = mergeConfig(JSON.parse(text));
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
      sshHostKey: config.car.sshHostKey,
      plinkPath: config.car.plinkPath,
      sshPrivateKey: config.car.sshPrivateKey
    },
    control: config.control,
    agent: {
      host: config.agent.host,
      port: config.agent.port,
      tokenSet: Boolean(config.agent.token),
      requestTimeoutMs: config.agent.requestTimeoutMs
    }
  };
}

export async function saveConfig(nextConfig) {
  activeConfig = mergeConfig(nextConfig);
  await writeFile(configPath, `${JSON.stringify(activeConfig, null, 2)}\n`, 'utf8');
  return activeConfig;
}
