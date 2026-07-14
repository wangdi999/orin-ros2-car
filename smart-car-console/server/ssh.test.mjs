import test from 'node:test';
import assert from 'node:assert/strict';
import { redactSensitiveText } from './ssh.mjs';

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
