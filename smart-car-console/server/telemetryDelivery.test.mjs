import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  TELEMETRY_MAX_BUFFERED_BYTES,
  TELEMETRY_MAX_LOGS,
  TelemetryDelivery
} from './telemetryDelivery.mjs';

function fakeSocket() {
  return {
    OPEN: 1,
    readyState: 1,
    bufferedAmount: 0,
    messages: [],
    send(message) {
      this.messages.push(JSON.parse(message));
    }
  };
}

function fakeScheduler() {
  const callbacks = [];
  return {
    callbacks,
    schedule(callback) {
      callbacks.push(callback);
      return callback;
    },
    cancel(callback) {
      const index = callbacks.indexOf(callback);
      if (index >= 0) callbacks.splice(index, 1);
    },
    flushNext() {
      callbacks.shift()?.();
    }
  };
}

test('telemetry delivery coalesces telemetry and nested runtime patches', () => {
  const ws = fakeSocket();
  const scheduler = fakeScheduler();
  const delivery = new TelemetryDelivery(ws, scheduler);

  delivery.queueTelemetry({ lidar: { points: [1] } });
  delivery.queueTelemetry({ lidar: { points: [2] }, voltage: { battery: 12.1 } });
  delivery.queueRuntimePatch({ command: { heartbeat: { connected: true } } });
  delivery.queueRuntimePatch({ command: { heartbeat: { ageMs: 20 } } });
  assert.equal(scheduler.callbacks.length, 1);

  scheduler.flushNext();
  assert.deepEqual(ws.messages, [
    { type: 'telemetry', data: { lidar: { points: [2] }, voltage: { battery: 12.1 } } },
    { type: 'runtime-patch', data: { command: { heartbeat: { connected: true, ageMs: 20 } } } }
  ]);
});

test('telemetry delivery retains only the latest pending state while socket is backpressured', () => {
  const ws = fakeSocket();
  ws.bufferedAmount = TELEMETRY_MAX_BUFFERED_BYTES + 1;
  const scheduler = fakeScheduler();
  const delivery = new TelemetryDelivery(ws, scheduler);

  delivery.queueTelemetry({ velocity: { linear: 0.1 } });
  scheduler.flushNext();
  delivery.queueTelemetry({ velocity: { linear: 0.2 } });
  assert.equal(ws.messages.length, 0);

  ws.bufferedAmount = 0;
  scheduler.flushNext();
  assert.deepEqual(ws.messages, [{ type: 'telemetry', data: { velocity: { linear: 0.2 } } }]);
});

test('telemetry delivery bounds logs and releases pending references on close', () => {
  const ws = fakeSocket();
  const scheduler = fakeScheduler();
  const delivery = new TelemetryDelivery(ws, scheduler);

  for (let index = 0; index <= TELEMETRY_MAX_LOGS; index += 1) delivery.queueLog({ index });
  assert.equal(delivery.logs.length, TELEMETRY_MAX_LOGS);
  assert.equal(delivery.logs[0].index, 1);

  delivery.queueSnapshot({ telemetry: { lidar: { points: [1] } } });
  delivery.close();
  scheduler.flushNext();
  assert.equal(ws.messages.length, 0);
  assert.equal(delivery.hasPending(), false);
});
