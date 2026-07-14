import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

test('heartbeat and connection loss auto-zero without latching emergency stop', async () => {
  const source = await readFile(new URL('./index.mjs', import.meta.url), 'utf8');
  for (const reason of ['Drive watchdog timeout', 'Telemetry WebSocket disconnected', 'ROSBridge disconnected']) {
    assert.match(source, new RegExp(`stopMotion\\('${reason.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}'\\)`));
    assert.doesNotMatch(source, new RegExp(`emergencyStop\\('${reason.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}'\\)`));
  }
  assert.match(source, /url\.pathname === '\/api\/emergency-stop'/);
});

test('browser unload sends zero drive and never triggers automatic emergency stop', async () => {
  const source = await readFile(new URL('../src/App.jsx', import.meta.url), 'utf8');
  assert.match(source, /beforeunload', stop/);
  assert.doesNotMatch(source, /sendBeacon\('\/api\/emergency-stop'/);
});
