import { readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const rootDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const configPath = path.join(rootDir, 'local-config.json');
const examplePath = path.join(rootDir, 'local-config.example.json');

const defaults = {
  car: {
    host: '192.168.160.196',
    sshUser: 'jetson',
    sshPassword: 'yahboom',
    sshHostKey: 'SHA256:AJffjk3YWwStux7ZbdKdft3teC8b7Jsubuvv4zMYuD8',
    plinkPath: 'D:\\putty\\plink.exe'
  },
  control: {
    maxLinearMps: 0.35,
    maxAngularRps: 1.2,
    deadZone: 0.05,
    watchdogMs: 450,
    commandTopic: '/cmd_vel'
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
      ...(config?.car ?? {})
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
      plinkPath: config.car.plinkPath
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
