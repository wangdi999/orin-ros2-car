export const DRIVE_KEY_CODES = new Set([
  'KeyW',
  'KeyA',
  'KeyS',
  'KeyD',
  'KeyQ',
  'KeyE',
  'ArrowUp',
  'ArrowDown',
  'ArrowLeft',
  'ArrowRight'
]);

export function isDriveKeyCode(code) {
  return DRIVE_KEY_CODES.has(code);
}

export function keyboardVectorFromCodes(codes) {
  const active = codes instanceof Set ? codes : new Set(codes ?? []);
  const forward = axis(active, ['KeyW', 'ArrowUp'], ['KeyS', 'ArrowDown']);
  const turn = axis(active, ['KeyD', 'ArrowRight'], ['KeyA', 'ArrowLeft']);
  const strafe = axis(active, ['KeyE'], ['KeyQ']);
  return {
    forward,
    turn,
    strafe
  };
}

function axis(active, positiveCodes, negativeCodes) {
  const positive = positiveCodes.some((code) => active.has(code)) ? 1 : 0;
  const negative = negativeCodes.some((code) => active.has(code)) ? 1 : 0;
  return positive - negative;
}
