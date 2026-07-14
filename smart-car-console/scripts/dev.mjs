import { spawn } from 'node:child_process';

const children = new Map();
const isWindows = process.platform === 'win32';
let shuttingDown = false;
let requestedExitCode = 0;

function stopChild(child, signal) {
  if (!child.pid || child.exitCode !== null || child.signalCode !== null) return;
  if (!isWindows) {
    try {
      process.kill(-child.pid, signal);
      return;
    } catch {
      // Fall back to the direct child if its process group has already exited.
    }
  }
  child.kill(signal);
}

function shutdown(exitCode, signal = 'SIGTERM') {
  if (shuttingDown) return;
  shuttingDown = true;
  requestedExitCode = exitCode;
  for (const child of children.values()) stopChild(child, signal);
  if (children.size === 0) process.exit(requestedExitCode);
}

const host = process.env.SMART_CAR_HOST?.trim();
if (host) {
  process.env.VITE_SMART_CAR_HOST = host;
  console.log(`小车IP: ${host}`);
}

function start(name, command, args) {
  const child = spawn(command, args, {
    stdio: 'inherit',
    shell: isWindows,
    detached: !isWindows
  });
  children.set(name, child);
  child.once('error', (error) => {
    console.error(`${name} failed to start: ${error.message}`);
    shutdown(1);
  });
  child.once('exit', (code, signal) => {
    children.delete(name);
    if (!shuttingDown) {
      console.error(`${name} exited unexpectedly (${signal || `code ${code ?? 1}`})`);
      shutdown(code && code !== 0 ? code : 1);
      return;
    }
    if (children.size === 0) process.exit(requestedExitCode);
  });
}

process.on('SIGINT', () => shutdown(0, 'SIGINT'));
process.on('SIGTERM', () => shutdown(0));

start('api', 'node', ['server/index.mjs']);
start('vite', 'npx', ['vite', '--host', '127.0.0.1', '--port', '5173']);
