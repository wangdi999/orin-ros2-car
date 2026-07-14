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

export function buildDriveCommand(input = {}, limits = {}, velocityFeedback = {}) {
  const maxLinearMps = clampNumber(limits.maxLinearMps, 0.02, 2, 0.35);
  const maxAngularRps = clampNumber(limits.maxAngularRps, 0.05, 4, 1.2);
  const deadZone = clampNumber(limits.deadZone, 0, 0.5, 0.05);
  const turnScale = clampNumber(limits.turnScale, -1, 1, -1);
  const requestedLinearLimit = clampNumber(input.linearLimit, 0, maxLinearMps, maxLinearMps);
  const requestedAngularLimit = clampNumber(input.angularLimit, 0, maxAngularRps, maxAngularRps);

  const forward = applyDeadZone(input.forward, deadZone);
  const strafe = applyDeadZone(input.strafe, deadZone);
  const turn = applyDeadZone(input.turn, deadZone);
  const straightAssist = computeStraightAssist(
    { forward, strafe, turn, requestedAngularLimit },
    limits.straightAssist,
    velocityFeedback
  );
  const angularZ = turn * requestedAngularLimit * turnScale + straightAssist.correctionAngular;

  return {
    twist: {
      linear: {
        x: roundCommand(forward * requestedLinearLimit),
        y: roundCommand(strafe * requestedLinearLimit),
        z: 0
      },
      angular: {
        x: 0,
        y: 0,
        z: roundCommand(angularZ)
      }
    },
    straightAssist
  };
}

export function buildTwistFromDriveInput(input = {}, limits = {}, velocityFeedback = {}) {
  return buildDriveCommand(input, limits, velocityFeedback).twist;
}

export function isZeroTwist(twist = ZERO_TWIST) {
  return Math.abs(twist.linear?.x ?? 0) < 0.001
    && Math.abs(twist.linear?.y ?? 0) < 0.001
    && Math.abs(twist.angular?.z ?? 0) < 0.001;
}

function computeStraightAssist(input, config = {}, feedback = {}) {
  const feedbackSample = feedback ?? {};
  const settings = normalizeStraightAssist(config);
  const feedbackAngular = finiteNumber(feedbackSample.angular);
  const feedbackAgeMs = feedbackAge(feedbackSample.updatedAt);
  const result = {
    enabled: settings.enabled,
    active: false,
    reason: null,
    feedbackAngular: feedbackAngular === null ? null : roundCommand(feedbackAngular),
    feedbackAgeMs,
    correctionAngular: 0
  };

  if (!settings.enabled) return { ...result, reason: 'disabled' };
  if (Math.abs(input.forward) < settings.minForwardInput) return { ...result, reason: 'below_min_forward' };
  if (Math.abs(input.turn) > 0 || Math.abs(input.strafe) > 0) return { ...result, reason: 'manual_axis' };
  if (input.requestedAngularLimit <= 0) return { ...result, reason: 'angular_limit_zero' };
  if (feedbackAngular === null) return { ...result, reason: 'no_feedback' };
  if (feedbackAgeMs === null || feedbackAgeMs > settings.feedbackMaxAgeMs) return { ...result, reason: 'stale_feedback' };
  if (Math.abs(feedbackAngular) <= settings.feedbackDeadZoneRps) return { ...result, reason: 'within_dead_zone' };

  const correctionLimit = Math.min(settings.maxCorrectionRps, input.requestedAngularLimit);
  const correction = clampNumber(
    feedbackAngular * settings.feedbackSign * settings.gain,
    -correctionLimit,
    correctionLimit,
    0
  );
  return {
    ...result,
    active: Math.abs(correction) >= 0.001,
    reason: Math.abs(correction) >= 0.001 ? 'correcting' : 'within_dead_zone',
    correctionAngular: roundCommand(correction)
  };
}

function normalizeStraightAssist(config = {}) {
  const source = config ?? {};
  return {
    enabled: source.enabled !== false,
    feedbackSign: clampNumber(source.feedbackSign, -1, 1, -1),
    gain: clampNumber(source.gain, 0, 5, 0.5),
    maxCorrectionRps: clampNumber(source.maxCorrectionRps, 0, 2, 0.25),
    feedbackDeadZoneRps: clampNumber(source.feedbackDeadZoneRps, 0, 1, 0.02),
    feedbackMaxAgeMs: clampNumber(source.feedbackMaxAgeMs, 0, 5000, 600),
    minForwardInput: clampNumber(source.minForwardInput, 0, 1, 0.2)
  };
}

function finiteNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function feedbackAge(updatedAt) {
  const timestamp = Date.parse(updatedAt);
  if (!Number.isFinite(timestamp)) return null;
  return Math.max(0, Date.now() - timestamp);
}
