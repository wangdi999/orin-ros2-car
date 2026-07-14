const DEFAULT_MAX_POINTS = 7000;

export function parsePointCloud2(msg, options = {}) {
  const maxPoints = Math.max(1, Number(options.maxPoints ?? DEFAULT_MAX_POINTS));
  const fields = Array.isArray(msg.fields) ? msg.fields : [];
  const pointStep = Number(msg.point_step);
  const width = Number(msg.width ?? 0);
  const height = Number(msg.height ?? 1);
  const totalPoints = Math.max(0, width * height);
  const data = decodeBinaryData(msg.data);
  const offsets = fieldOffsets(fields);

  if (!data || !Number.isFinite(pointStep) || pointStep <= 0 || totalPoints === 0 || !hasCoordinates(offsets)) {
    return {
      connected: false,
      topic: null,
      frameId: msg.header?.frame_id ?? null,
      width,
      height,
      totalPoints,
      points: [],
      lastError: 'PointCloud2 message is missing coordinate fields or binary data'
    };
  }

  const littleEndian = !msg.is_bigendian;
  const view = new DataView(data.buffer, data.byteOffset, data.byteLength);
  const stride = Math.max(1, Math.ceil(totalPoints / maxPoints));
  const points = [];
  const bounds = emptyBounds();

  for (let index = 0; index < totalPoints; index += stride) {
    const base = index * pointStep;
    if (base + pointStep > data.byteLength) break;
    const x = readFloat32(view, base + offsets.x, littleEndian);
    const y = readFloat32(view, base + offsets.y, littleEndian);
    const z = readFloat32(view, base + offsets.z, littleEndian);
    if (!Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(z)) continue;
    const color = readColor(view, base, offsets, littleEndian, z);
    points.push({ x: round(x), y: round(y), z: round(z), color });
    expandBounds(bounds, x, y, z);
  }

  return {
    connected: true,
    frameId: msg.header?.frame_id ?? null,
    width,
    height,
    totalPoints,
    sampledPoints: points.length,
    bounds: finalizeBounds(bounds),
    points
  };
}

function decodeBinaryData(data) {
  if (typeof data === 'string') return Buffer.from(data, 'base64');
  if (Array.isArray(data)) return Buffer.from(data);
  if (ArrayBuffer.isView(data)) return Buffer.from(data.buffer, data.byteOffset, data.byteLength);
  return null;
}

function fieldOffsets(fields) {
  const offsets = {};
  for (const field of fields) {
    if (field?.name) offsets[field.name] = Number(field.offset);
  }
  return offsets;
}

function hasCoordinates(offsets) {
  return Number.isFinite(offsets.x) && Number.isFinite(offsets.y) && Number.isFinite(offsets.z);
}

function readFloat32(view, offset, littleEndian) {
  if (!Number.isFinite(offset) || offset < 0 || offset + 4 > view.byteLength) return NaN;
  return view.getFloat32(offset, littleEndian);
}

function readColor(view, base, offsets, littleEndian, z) {
  const rgbOffset = Number.isFinite(offsets.rgb) ? offsets.rgb : offsets.rgba;
  if (Number.isFinite(rgbOffset) && base + rgbOffset + 4 <= view.byteLength) {
    const packed = view.getUint32(base + rgbOffset, littleEndian);
    return `#${((packed >> 16) & 0xff).toString(16).padStart(2, '0')}${((packed >> 8) & 0xff).toString(16).padStart(2, '0')}${(packed & 0xff).toString(16).padStart(2, '0')}`;
  }
  const normalized = Math.max(0, Math.min(1, (z + 1) / 4));
  const hue = Math.round(220 - normalized * 170);
  return hslToHex(hue, 90, 52);
}

function hslToHex(h, s, l) {
  s /= 100;
  l /= 100;
  const k = (n) => (n + h / 30) % 12;
  const a = s * Math.min(l, 1 - l);
  const f = (n) => l - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1)));
  return `#${[f(0), f(8), f(4)].map((value) => Math.round(255 * value).toString(16).padStart(2, '0')).join('')}`;
}

function emptyBounds() {
  return {
    minX: Infinity,
    maxX: -Infinity,
    minY: Infinity,
    maxY: -Infinity,
    minZ: Infinity,
    maxZ: -Infinity
  };
}

function expandBounds(bounds, x, y, z) {
  bounds.minX = Math.min(bounds.minX, x);
  bounds.maxX = Math.max(bounds.maxX, x);
  bounds.minY = Math.min(bounds.minY, y);
  bounds.maxY = Math.max(bounds.maxY, y);
  bounds.minZ = Math.min(bounds.minZ, z);
  bounds.maxZ = Math.max(bounds.maxZ, z);
}

function finalizeBounds(bounds) {
  for (const value of Object.values(bounds)) {
    if (!Number.isFinite(value)) return null;
  }
  return Object.fromEntries(Object.entries(bounds).map(([key, value]) => [key, round(value)]));
}

function round(value) {
  return Math.round(value * 1000) / 1000;
}
