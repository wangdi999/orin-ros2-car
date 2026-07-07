import { spawn } from 'node:child_process';

const children = [];
const isWindows = process.platform === 'win32';

function start(name, command, args) {
  const child = spawn(command, args, {
    stdio: 'inherit',
    shell: isWindows
  });
  children.push(child);
  child.on('exit', (code) => {
    if (code && code !== 0) {
      console.error(`${name} exited with code ${code}`);
    }
  });
}

process.on('SIGINT', () => {
  for (const child of children) child.kill('SIGINT');
  process.exit(0);
});

start('api', 'node', ['server/index.mjs']);
start('vite', 'npx', ['vite', '--host', '127.0.0.1', '--port', '5173']);
