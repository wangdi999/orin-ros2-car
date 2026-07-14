import assert from 'node:assert/strict';
import { test } from 'node:test';
import { buildSshInvocation, redactSensitiveText, resolvePlinkExecutable, SshExecutor } from './ssh.mjs';

test('unconfigured car host fails closed before spawning SSH', async () => {
  const executor = new SshExecutor(() => ({ car: { host: '' } }), () => {});
  const result = await executor.run('true');
  assert.equal(result.ok, false);
  assert.equal(result.stderr, 'Car host is not configured');
});

test('SSH output redacts configured credentials and fingerprint-shaped host keys', () => {
  const config = { car: { sshPassword: 'do-not-print', sshHostKey: 'SHA256:abcdefghijklmnopqrstuvwx' } };
  const output = redactSensitiveText(
    'password=do-not-print host key: SHA256:abcdefghijklmnopqrstuvwx token=abc123',
    config
  );
  assert.equal(output.includes('do-not-print'), false);
  assert.equal(output.includes('abcdefghijklmnopqrstuvwx'), false);
  assert.equal(output.includes('abc123'), false);
});

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
