import assert from 'node:assert/strict';
import { test } from 'node:test';
import { hasSafeControlStack } from './serviceManager.mjs';

const safeStatus = {
  services: {
    docker: true,
    chassis: true,
    arbiter: true,
    lidar: true,
    rosbridge: true
  }
};

test('existing safe stack can be reused by the console', () => {
  assert.equal(hasSafeControlStack(safeStatus), true);
});

test('console refuses a stack without the command arbiter', () => {
  assert.equal(
    hasSafeControlStack({ services: { ...safeStatus.services, arbiter: false } }),
    false
  );
});
