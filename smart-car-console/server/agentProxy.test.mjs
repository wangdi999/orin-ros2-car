import assert from 'node:assert/strict';
import test from 'node:test';
import { buildAgentMotionStopRequest, buildAgentTarget } from './agentProxy.mjs';


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

test('console stop uses the agent motion gateway instead of ROSBridge', () => {
  const request = buildAgentMotionStopRequest(config, 'Browser lost focus');

  assert.equal(request.path, '/api/v1/agent/motion/execute');
  assert.equal(request.body.intent.action, 'STOP');
  assert.equal(request.body.confirmed, true);
  assert.equal(request.body.operator, 'web-console');
});
