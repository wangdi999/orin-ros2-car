import assert from 'node:assert/strict';
import { test } from 'node:test';
import { buildTwistFromDriveInput, isZeroTwist } from './control.mjs';

const limits = {
  maxLinearMps: 0.35,
  maxAngularRps: 1.2,
  deadZone: 0.05
};

test('dead-zone maps small joystick input to zero twist', () => {
  const twist = buildTwistFromDriveInput({ forward: 0.02, turn: -0.04 }, limits);
  assert.equal(isZeroTwist(twist), true);
});

test('input is clamped before converting to Twist', () => {
  const twist = buildTwistFromDriveInput({ forward: 4, strafe: -3, turn: 2 }, limits);
  assert.equal(twist.linear.x, 0.35);
  assert.equal(twist.linear.y, -0.35);
  assert.equal(twist.angular.z, 1.2);
});

test('user speed limit caps linear and angular output', () => {
  const twist = buildTwistFromDriveInput({
    forward: 1,
    turn: -1,
    linearLimit: 0.12,
    angularLimit: 0.5
  }, limits);
  assert.equal(twist.linear.x, 0.12);
  assert.equal(twist.angular.z, -0.5);
});

test('invalid payload values fall back to a stopped command', () => {
  const twist = buildTwistFromDriveInput({ forward: 'bad', turn: Number.NaN }, limits);
  assert.equal(isZeroTwist(twist), true);
});
