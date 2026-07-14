import test from 'node:test';
import assert from 'node:assert/strict';
import { getConfig, mergeApiConfig, parseConfigText, publicConfig } from './config.mjs';

test('config parser accepts a UTF-8 BOM', () => {
  assert.deepEqual(parseConfigText('\uFEFF{"control":{"heartbeatProtectionEnabled":false}}'), {
    control: { heartbeatProtectionEnabled: false }
  });
});

test('public config exposes only credential presence flags', () => {
  const config = publicConfig();
  const json = JSON.stringify(config);
  assert.equal(json.includes('SHA256:'), false);
  assert.equal(json.includes('plink.exe'), false);
  assert.equal('sshHostKey' in config.car, false);
  assert.equal('plinkPath' in config.car, false);
});

test('API config cannot replace executable path or SSH host key', () => {
  const current = getConfig();
  const merged = mergeApiConfig(current, {
    car: {
      host: '192.168.43.137',
      sshUser: 'jetson',
      sshHostKey: 'attacker-key',
      plinkPath: 'C:\\malware.exe'
    }
  });
  assert.equal(merged.car.sshHostKey, current.car.sshHostKey);
  assert.equal(merged.car.plinkPath, current.car.plinkPath);
});
