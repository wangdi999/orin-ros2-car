import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';

const WSL_PLINK_CANDIDATES = [
  '/mnt/c/Program Files/PuTTY/plink.exe',
  '/mnt/c/Program Files (x86)/PuTTY/plink.exe'
];

export function resolvePlinkExecutable(
  configuredPath,
  { platform = process.platform, exists = existsSync } = {}
) {
  const value = String(configuredPath || 'plink').trim();
  if (platform === 'win32') return value;

  const windowsMatch = value.match(/^([a-z]):[\\/](.*)$/i);
  const converted = windowsMatch
    ? `/mnt/${windowsMatch[1].toLowerCase()}/${windowsMatch[2].replaceAll('\\', '/')}`
    : null;
  const candidates = [value, converted, ...WSL_PLINK_CANDIDATES].filter(Boolean);
  return candidates.find((candidate) => exists(candidate)) || converted || value;
}

export function buildSshInvocation(
  config,
  { platform = process.platform, exists = existsSync } = {}
) {
  const privateKey = String(config.car.sshPrivateKey || '').trim();
  if (platform !== 'win32' && privateKey && exists(privateKey)) {
    return {
      command: 'ssh',
      args: [
        '-i',
        privateKey,
        '-o',
        'IdentitiesOnly=yes',
        '-o',
        'BatchMode=yes',
        '-o',
        'StrictHostKeyChecking=yes',
        '-o',
        'ConnectTimeout=8',
        `${config.car.sshUser}@${config.car.host}`
      ]
    };
  }
  return {
    command: resolvePlinkExecutable(config.car.plinkPath, { platform, exists }),
    args: [
      '-ssh',
      '-batch',
      '-hostkey',
      config.car.sshHostKey,
      '-pw',
      config.car.sshPassword,
      `${config.car.sshUser}@${config.car.host}`
    ]
  };
}

export class SshExecutor {
  constructor(getConfig, logger) {
    this.getConfig = getConfig;
    this.logger = logger;
  }

  async run(command, options = {}) {
    const config = this.getConfig();
    const timeoutMs = options.timeoutMs ?? 12000;
    const bashScript = typeof command === 'object' && command?.kind === 'bash-script';
    const commandText = bashScript ? command.script : command;
    const invocation = buildSshInvocation(config);
    const args = [...invocation.args, ...(bashScript ? ['bash', '-s'] : [commandText])];

    const startedAt = Date.now();
    return await new Promise((resolve) => {
      let child;
      try {
        child = spawn(invocation.command, args, {
          windowsHide: true,
          stdio: [bashScript ? 'pipe' : 'ignore', 'pipe', 'pipe']
        });
        if (bashScript) child.stdin.end(command.script);
      } catch (error) {
        resolve({
          ok: false,
          code: null,
          stdout: '',
          stderr: error.message,
          timedOut: false,
          durationMs: Date.now() - startedAt,
          command: commandText
        });
        return;
      }
      let stdout = '';
      let stderr = '';
      let timedOut = false;

      const timer = setTimeout(() => {
        timedOut = true;
        child.kill('SIGTERM');
      }, timeoutMs);

      child.stdout.on('data', (chunk) => {
        stdout += chunk.toString('utf8');
      });
      child.stderr.on('data', (chunk) => {
        stderr += chunk.toString('utf8');
      });
      child.on('error', (error) => {
        clearTimeout(timer);
        resolve({
          ok: false,
          code: null,
          stdout,
          stderr: error.message,
          timedOut,
          durationMs: Date.now() - startedAt,
          command: commandText
        });
      });
      child.on('close', (code) => {
        clearTimeout(timer);
        resolve({
          ok: code === 0 && !timedOut,
          code,
          stdout,
          stderr,
          timedOut,
          durationMs: Date.now() - startedAt,
          command: commandText
        });
      });
    });
  }
}

export function shellQuote(value) {
  return `'${String(value).replaceAll("'", "'\\''")}'`;
}

export function bash(command) {
  return {
    kind: 'bash-script',
    script: command
  };
}
