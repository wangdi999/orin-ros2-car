export const JOYSTICK_ALPHA = 0.3;
export const DRIVE_PUBLISH_INTERVAL_MS = 50;
export const HEARTBEAT_INTERVAL_MS = 100;
export const WATCHDOG_TIMEOUT_MS = 500;

export function smoothJoystickVector(previous = {}, target = {}, alpha = JOYSTICK_ALPHA) {
  const mix = clamp(alpha, 0, 1);
  return {
    forward: roundAxis(lerp(axis(previous.forward), axis(target.forward), mix)),
    turn: roundAxis(lerp(axis(previous.turn), axis(target.turn), mix)),
    strafe: roundAxis(lerp(axis(previous.strafe), axis(target.strafe), mix))
  };
}

export function hasMotion(vector = {}, epsilon = 0.01) {
  return Math.abs(axis(vector.forward)) > epsilon
    || Math.abs(axis(vector.turn)) > epsilon
    || Math.abs(axis(vector.strafe)) > epsilon;
}

function lerp(from, to, alpha) {
  return from + (to - from) * alpha;
}

function axis(value) {
  const number = Number(value);
  return Number.isFinite(number) ? clamp(number, -1, 1) : 0;
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function roundAxis(value) {
  return Math.round(value * 1000) / 1000;
}
