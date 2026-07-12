import assert from 'node:assert/strict';
import test from 'node:test';
import { buildAgentTarget } from './agentProxy.mjs';


const config = {
  car: { host: '192.168.1.20' },
  agent: { host: '', port: 8100, token: 'secret', requestTimeoutMs: 15000 }
};

test('agent API path is mapped to /api/v1', () => {
  assert.deepEqual(buildAgentTarget(config, '/api/agent/tasks/current', '?a=1'), {
    host: '192.168.1.20',
    port: 8100,
    path: '/api/v1/tasks/current?a=1',
    token: 'secret',
    timeoutMs: 15000
  });
});

test('health path bypasses /api/v1 prefix', () => {
  assert.equal(buildAgentTarget(config, '/api/agent/health').path, '/health');
});
