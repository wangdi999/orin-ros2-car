import assert from 'node:assert/strict';
import { test } from 'node:test';
import { buildSshInvocation, resolvePlinkExecutable } from './ssh.mjs';

test('Windows keeps the configured PuTTY path', () => {
  const path = 'C:\\Program Files\\PuTTY\\plink.exe';
  assert.equal(resolvePlinkExecutable(path, { platform: 'win32' }), path);
});

test('WSL converts an existing Windows path', () => {
  const expected = '/mnt/d/putty/plink.exe';
  assert.equal(
    resolvePlinkExecutable('D:\\putty\\plink.exe', {
      platform: 'linux',
      exists: (candidate) => candidate === expected
    }),
    expected
  );
});

test('WSL falls back to the standard PuTTY installation', () => {
  const expected = '/mnt/c/Program Files/PuTTY/plink.exe';
  assert.equal(
    resolvePlinkExecutable('D:\\putty\\plink.exe', {
      platform: 'linux',
      exists: (candidate) => candidate === expected
    }),
    expected
  );
});

test('Linux uses native OpenSSH when a private key is configured', () => {
  const key = '/home/test/.ssh/car';
  const config = {
    car: {
      host: '10.77.0.2',
      sshUser: 'jetson',
      sshPassword: 'unused',
      sshHostKey: 'SHA256:test',
      plinkPath: 'C:\\Program Files\\PuTTY\\plink.exe',
      sshPrivateKey: key
    }
  };

  const invocation = buildSshInvocation(config, {
    platform: 'linux',
    exists: (candidate) => candidate === key
  });

  assert.equal(invocation.command, 'ssh');
  assert.deepEqual(invocation.args.slice(0, 3), ['-i', key, '-o']);
  assert.equal(invocation.args.at(-1), 'jetson@10.77.0.2');
  assert.equal(invocation.args.includes('unused'), false);
});
