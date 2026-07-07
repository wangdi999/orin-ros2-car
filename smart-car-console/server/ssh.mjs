import { spawn } from 'node:child_process';

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
