import { spawn } from 'node:child_process';

function escapeRegex(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

export function redactSensitiveText(value, config = {}) {
  let text = String(value ?? '');
  for (const secret of [config?.car?.sshPassword, config?.car?.sshHostKey]) {
    if (secret) text = text.replace(new RegExp(escapeRegex(secret), 'g'), '[REDACTED]');
  }
  text = text.replace(/SHA256:[A-Za-z0-9+/=]{16,}/g, '[REDACTED_HOST_KEY]');
  text = text.replace(/\b(password|passwd|token|secret|host[ _-]?key)\b\s*[:=]\s*[^\s,;]+/gi, '$1=[REDACTED]');
  return text;
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
    const args = [
      '-ssh',
      '-batch',
      '-hostkey',
      config.car.sshHostKey,
      '-pw',
      config.car.sshPassword,
      `${config.car.sshUser}@${config.car.host}`,
      ...(bashScript ? ['bash', '-s'] : [commandText])
    ];

    const startedAt = Date.now();
    const safe = (value) => redactSensitiveText(value, config);
    return await new Promise((resolve) => {
      let child;
      try {
        child = spawn(config.car.plinkPath, args, {
          windowsHide: true,
          stdio: [bashScript ? 'pipe' : 'ignore', 'pipe', 'pipe']
        });
        if (bashScript) child.stdin.end(command.script);
      } catch (error) {
        resolve({
          ok: false,
          code: null,
          stdout: '',
          stderr: safe(error.message),
          timedOut: false,
          durationMs: Date.now() - startedAt,
          command: safe(commandText)
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
          stdout: safe(stdout),
          stderr: safe(error.message),
          timedOut,
          durationMs: Date.now() - startedAt,
          command: safe(commandText)
        });
      });
      child.on('close', (code) => {
        clearTimeout(timer);
        resolve({
          ok: code === 0 && !timedOut,
          code,
          stdout: safe(stdout),
          stderr: safe(stderr),
          timedOut,
          durationMs: Date.now() - startedAt,
          command: safe(commandText)
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
