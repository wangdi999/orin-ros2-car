export const ZERO_TWIST = Object.freeze({
  linear: Object.freeze({ x: 0, y: 0, z: 0 }),
  angular: Object.freeze({ x: 0, y: 0, z: 0 })
});

export function clampNumber(value, min, max, fallback = 0) {
  const number = Number(value);
  if (!Number.isFinite(number)) return fallback;
  return Math.min(max, Math.max(min, number));
}

export function applyDeadZone(value, deadZone) {
  const normalized = clampNumber(value, -1, 1, 0);
  const zone = clampNumber(deadZone, 0, 0.9, 0);
  const magnitude = Math.abs(normalized);
  if (magnitude <= zone) return 0;
  return Math.sign(normalized) * ((magnitude - zone) / (1 - zone));
}

export function roundCommand(value) {
  return Math.round(value * 1000) / 1000;
}

export function buildTwistFromDriveInput(input = {}, limits = {}) {
  const maxLinearMps = clampNumber(limits.maxLinearMps, 0.02, 2, 0.35);
  const maxAngularRps = clampNumber(limits.maxAngularRps, 0.05, 4, 1.2);
  const deadZone = clampNumber(limits.deadZone, 0, 0.5, 0.05);
  const requestedLinearLimit = clampNumber(input.linearLimit, 0, maxLinearMps, maxLinearMps);
  const requestedAngularLimit = clampNumber(input.angularLimit, 0, maxAngularRps, maxAngularRps);

  const forward = applyDeadZone(input.forward, deadZone);
  const strafe = applyDeadZone(input.strafe, deadZone);
  const turn = applyDeadZone(input.turn, deadZone);

  return {
    linear: {
      x: roundCommand(forward * requestedLinearLimit),
      y: roundCommand(strafe * requestedLinearLimit),
      z: 0
    },
    angular: {
      x: 0,
      y: 0,
      z: roundCommand(turn * requestedAngularLimit)
    }
  };
}

export function isZeroTwist(twist = ZERO_TWIST) {
  return Math.abs(twist.linear?.x ?? 0) < 0.001
    && Math.abs(twist.linear?.y ?? 0) < 0.001
    && Math.abs(twist.angular?.z ?? 0) < 0.001;
}
