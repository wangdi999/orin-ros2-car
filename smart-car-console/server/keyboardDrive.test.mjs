import assert from 'node:assert/strict';
import { test } from 'node:test';
import { isDriveKeyCode, keyboardVectorFromCodes } from '../src/keyboardDrive.js';

test('WASD maps to forward/back and turn axes', () => {
  assert.deepEqual(keyboardVectorFromCodes(['KeyW']), { forward: 1, turn: 0, strafe: 0 });
  assert.deepEqual(keyboardVectorFromCodes(['KeyS']), { forward: -1, turn: 0, strafe: 0 });
  assert.deepEqual(keyboardVectorFromCodes(['KeyA']), { forward: 0, turn: -1, strafe: 0 });
  assert.deepEqual(keyboardVectorFromCodes(['KeyD']), { forward: 0, turn: 1, strafe: 0 });
});

test('opposite keyboard directions cancel each other', () => {
  assert.deepEqual(keyboardVectorFromCodes(['KeyW', 'KeyS', 'KeyA', 'KeyD']), {
    forward: 0,
    turn: 0,
    strafe: 0
  });
});

test('Q and E map to mecanum lateral movement', () => {
  assert.deepEqual(keyboardVectorFromCodes(['KeyQ']), { forward: 0, turn: 0, strafe: -1 });
  assert.deepEqual(keyboardVectorFromCodes(['KeyE']), { forward: 0, turn: 0, strafe: 1 });
});

test('arrow keys mirror WASD movement', () => {
  assert.deepEqual(keyboardVectorFromCodes(['ArrowUp', 'ArrowLeft']), {
    forward: 1,
    turn: -1,
    strafe: 0
  });
});

test('only drive keys are handled by global keyboard control', () => {
  assert.equal(isDriveKeyCode('KeyW'), true);
  assert.equal(isDriveKeyCode('Space'), false);
  assert.equal(isDriveKeyCode('Enter'), false);
});
