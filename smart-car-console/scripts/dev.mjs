import { spawn } from 'node:child_process';
import { createInterface } from 'node:readline';

const children = [];
const isWindows = process.platform === 'win32';

function askIP() {
  return new Promise((resolve) => {
    const rl = createInterface({ input: process.stdin, output: process.stdout });
    rl.question('小车IP: ', (answer) => {
      rl.close();
      resolve(answer.trim() || '192.168.160.196');
    });
  });
}

const host = process.env.SMART_CAR_HOST || await askIP();
process.env.SMART_CAR_HOST = host;
process.env.VITE_SMART_CAR_HOST = host;
console.log(`小车IP: ${host}`);

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
