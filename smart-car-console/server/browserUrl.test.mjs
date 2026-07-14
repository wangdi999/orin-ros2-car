import assert from 'node:assert/strict';
import { test } from 'node:test';
import { sameOriginWebSocketUrl } from '../src/browserUrl.js';

test('development websocket stays on the Vite origin', () => {
  assert.equal(
    sameOriginWebSocketUrl('/api/telemetry', {
      protocol: 'http:',
      host: 'localhost:5173'
    }),
    'ws://localhost:5173/api/telemetry'
  );
});

test('https pages use secure same-origin websockets', () => {
  assert.equal(
    sameOriginWebSocketUrl('api/agent/events', {
      protocol: 'https:',
      host: 'tools.example.test'
    }),
    'wss://tools.example.test/api/agent/events'
  );
});
