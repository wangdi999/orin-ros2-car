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
  assert.equal(twist.angular.z, -1.2);
});

test('user speed limit caps linear and angular output', () => {
  const twist = buildTwistFromDriveInput({
    forward: 1,
    turn: -1,
    linearLimit: 0.12,
    angularLimit: 0.5
  }, limits);
  assert.equal(twist.linear.x, 0.12);
  assert.equal(twist.angular.z, 0.5);
});

test('invalid payload values fall back to a stopped command', () => {
  const twist = buildTwistFromDriveInput({ forward: 'bad', turn: Number.NaN }, limits);
  assert.equal(isZeroTwist(twist), true);
});

test('straight keyboard movement has zero angular command without feedback drift', () => {
  const twist = buildTwistFromDriveInput({ forward: 1, turn: 0, linearLimit: 0.1, angularLimit: 0.3 }, limits);
  assert.equal(twist.linear.x, 0.1);
  assert.equal(twist.angular.z, 0);
});

test('fresh velocity feedback adds bounded straight-line correction', () => {
  const twist = buildTwistFromDriveInput(
    { forward: 1, turn: 0, linearLimit: 0.1, angularLimit: 0.3 },
    limits,
    { angular: 0.2, updatedAt: new Date().toISOString() }
  );
  assert.equal(twist.angular.z, -0.1);
});

test('straight-line correction respects correction and angular limits', () => {
  const twist = buildTwistFromDriveInput(
    { forward: 1, turn: 0, linearLimit: 0.1, angularLimit: 0.12 },
    limits,
    { angular: 2, updatedAt: new Date().toISOString() }
  );
  assert.equal(twist.angular.z, -0.12);
});

test('manual turn, strafe, zero movement, and stale feedback do not trigger correction', () => {
  const freshFeedback = { angular: 0.2, updatedAt: new Date().toISOString() };
  const staleFeedback = { angular: 0.2, updatedAt: new Date(Date.now() - 2000).toISOString() };

  assert.equal(buildTwistFromDriveInput({ forward: 1, turn: 1, angularLimit: 0.3 }, limits, freshFeedback).angular.z, -0.3);
  assert.equal(buildTwistFromDriveInput({ forward: 1, strafe: 1, angularLimit: 0.3 }, limits, freshFeedback).angular.z, 0);
  assert.equal(buildTwistFromDriveInput({ forward: 0, turn: 0, angularLimit: 0.3 }, limits, freshFeedback).angular.z, 0);
  assert.equal(buildTwistFromDriveInput({ forward: 1, turn: 0, angularLimit: 0.3 }, limits, staleFeedback).angular.z, 0);
});
