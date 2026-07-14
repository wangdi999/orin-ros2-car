const MAX_MAP_PREVIEW_SIDE = 260;
const MAX_PATH_POINTS = 260;
export const REALTIME_STALE_MS = 5000;

export function parseOccupancyGrid(msg = {}) {
  const info = msg.info ?? {};
  const width = integer(info.width);
  const height = integer(info.height);
  const resolution = finite(info.resolution);
  const raw = Array.isArray(msg.data) ? msg.data : [];
  const origin = parsePose2d(info.origin);
  if (!width || !height || resolution === null || resolution <= 0
    || raw.length < width * height
    || origin.x === null || origin.y === null || origin.yaw === null) {
    return {
      connected: false,
      mode: 'map',
      lastError: 'OccupancyGrid is missing info or data'
    };
  }

  const step = Math.max(1, Math.ceil(Math.max(width, height) / MAX_MAP_PREVIEW_SIDE));
  const previewWidth = Math.ceil(width / step);
  const previewHeight = Math.ceil(height / step);
  const cells = [];
  let occupied = 0;
  let free = 0;
  let unknown = 0;

  for (let y = 0; y < height; y += step) {
    for (let x = 0; x < width; x += step) {
      let value = -1;
      for (let blockY = y; blockY < Math.min(height, y + step); blockY += 1) {
        for (let blockX = x; blockX < Math.min(width, x + step); blockX += 1) {
          const candidate = normalizeCell(raw[blockY * width + blockX]);
          if (candidate >= 0) value = Math.max(value, candidate);
        }
      }
      if (value < 0) unknown += 1;
      else if (value >= 65) occupied += 1;
      else free += 1;
      cells.push(value);
    }
  }

  return {
    connected: true,
    mode: 'map',
    frameId: msg.header?.frame_id ?? null,
    width,
    height,
    previewWidth,
    previewHeight,
    step,
    resolution,
    origin,
    occupied,
    free,
    unknown,
    cells
  };
}

export function parseOdometry(msg = {}) {
  const pose = parsePose2d(msg.pose?.pose);
  const twist = msg.twist?.twist ?? {};
  return {
    connected: pose.x !== null && pose.y !== null,
    frameId: msg.header?.frame_id ?? null,
    childFrameId: msg.child_frame_id ?? null,
    pose,
    linear: round(twist.linear?.x),
    angular: round(twist.angular?.z)
  };
}

export function parsePoseWithCovariance(msg = {}) {
  const pose = parsePose2d(msg.pose?.pose);
  return {
    connected: pose.x !== null && pose.y !== null,
    frameId: msg.header?.frame_id ?? null,
    childFrameId: null,
    source: 'amcl',
    pose,
    covariance: Array.isArray(msg.pose?.covariance) ? msg.pose.covariance.slice(0, 36) : []
  };
}

export function parsePath(msg = {}) {
  const poses = Array.isArray(msg.poses) ? msg.poses : [];
  const frameId = normalizeFrame(msg.header?.frame_id) || null;
  const validPoses = poses.flatMap((entry) => {
    const poseFrame = normalizeFrame(entry?.header?.frame_id);
    const point = parsePose2d(entry?.pose);
    if ((frameId && poseFrame && poseFrame !== frameId)
      || point.x === null || point.y === null || point.yaw === null) return [];
    return [point];
  });
  const step = validPoses.length > MAX_PATH_POINTS
    ? Math.ceil((validPoses.length - 1) / (MAX_PATH_POINTS - 1))
    : 1;
  const indices = [];
  for (let index = 0; index < validPoses.length; index += step) indices.push(index);
  if (validPoses.length > 0 && indices.at(-1) !== validPoses.length - 1) indices.push(validPoses.length - 1);
  const points = indices.map((index) => validPoses[index]);
  return {
    connected: Boolean(msg.header) || Array.isArray(msg.poses),
    empty: validPoses.length === 0,
    frameId,
    totalPoints: poses.length,
    invalidPoints: poses.length - validPoses.length,
    step,
    points
  };
}

export class Tf2dBuffer {
  constructor() {
    this.transforms = new Map();
  }

  update(msg = {}, receivedAt = new Date().toISOString(), isStatic = false) {
    for (const item of msg.transforms ?? []) {
      const parent = normalizeFrame(item.header?.frame_id);
      const child = normalizeFrame(item.child_frame_id);
      if (!parent || !child) continue;
      const translation = item.transform?.translation ?? {};
      const transform = {
        parent,
        child,
        x: round(translation.x, 4) ?? 0,
        y: round(translation.y, 4) ?? 0,
        yaw: quaternionYaw(item.transform?.rotation),
        updatedAt: receivedAt,
        static: Boolean(isStatic)
      };
      if (transform.yaw === null) continue;
      this.transforms.set(`${parent}->${child}`, transform);
    }
  }

  clear() {
    this.transforms.clear();
  }

  resolve(parentFrame, childFrame) {
    const parent = normalizeFrame(parentFrame);
    const child = normalizeFrame(childFrame);
    if (!parent || !child) return unavailableTf(parent, child);
    if (parent === child) {
      return tfPose({ parent, child, x: 0, y: 0, yaw: 0, updatedAt: null, static: true }, []);
    }
    const graph = new Map();
    const addEdge = (from, edge) => graph.set(from, [...(graph.get(from) ?? []), edge]);
    for (const transform of this.transforms.values()) {
      addEdge(transform.parent, transform);
      addEdge(transform.child, inverseTransform(transform));
    }
    const identity = { parent, child: parent, x: 0, y: 0, yaw: 0, updatedAt: null, static: true };
    const queue = [{ frame: parent, transform: identity, sources: [] }];
    const visited = new Set([parent]);
    while (queue.length > 0) {
      const current = queue.shift();
      for (const edge of graph.get(current.frame) ?? []) {
        if (visited.has(edge.child)) continue;
        const transform = composeTransform(current.transform, edge);
        const sources = [...current.sources, edge];
        if (edge.child === child) return tfPose(transform, sources);
        visited.add(edge.child);
        if (sources.length < 32) queue.push({ frame: edge.child, transform, sources });
      }
    }
    return unavailableTf(parent, child);
  }
}

export function resolveMapPose({ amcl, tfPose: tf, odom } = {}, now = new Date().toISOString()) {
  if (isFresh(amcl, now) && normalizeFrame(amcl.frameId) === 'map') {
    return { ...amcl, source: 'amcl' };
  }
  if (isFresh(tf, now) && normalizeFrame(tf.frameId) === 'map') {
    return { ...tf, source: 'tf' };
  }
  if (isFresh(odom, now) && normalizeFrame(odom.frameId) === 'map') {
    return { ...odom, source: 'map-frame-odometry' };
  }
  return {
    connected: false,
    frameId: 'map',
    childFrameId: 'base_footprint',
    source: null,
    pose: { x: null, y: null, yaw: null },
    updatedAt: null,
    reason: 'No fresh AMCL or map-frame TF pose; odom coordinates are not drawn on the global map'
  };
}

export function withFreshness(sample, now = new Date().toISOString(), staleMs = REALTIME_STALE_MS) {
  if (!sample || typeof sample !== 'object') return sample;
  const updated = Date.parse(sample.updatedAt);
  const current = Date.parse(now);
  const ageMs = Number.isFinite(updated) && Number.isFinite(current)
    ? Math.max(0, current - updated)
    : null;
  const stale = ageMs === null || ageMs > staleMs;
  return {
    ...sample,
    ageMs,
    stale,
    disconnectedReason: stale
      ? (ageMs === null ? '尚未收到真实数据' : '超过 5 秒未收到新数据，保留最后一次真实采样')
      : null
  };
}

export function localOccupancyFromScan(scan = {}) {
  const points = Array.isArray(scan.points) ? scan.points : [];
  return {
    connected: Boolean(scan.connected),
    mode: 'scan',
    frameId: scan.frameId ?? null,
    rangeMax: scan.rangeMax ?? 12,
    points,
    note: 'Local lidar view; global /map is not available'
  };
}

function parsePose2d(pose = {}) {
  return {
    x: round(pose.position?.x),
    y: round(pose.position?.y),
    yaw: quaternionYaw(pose.orientation)
  };
}

function normalizeFrame(value) {
  return String(value ?? '').replace(/^\/+/, '');
}

function composeTransform(first, second) {
  const cos = Math.cos(first.yaw);
  const sin = Math.sin(first.yaw);
  return {
    parent: first.parent,
    child: second.child,
    x: round(first.x + cos * second.x - sin * second.y, 4),
    y: round(first.y + sin * second.x + cos * second.y, 4),
    yaw: normalizeAngle(first.yaw + second.yaw),
    updatedAt: combinedDynamicTimestamp(first, second),
    static: first.static && second.static
  };
}

function inverseTransform(transform) {
  const cos = Math.cos(transform.yaw);
  const sin = Math.sin(transform.yaw);
  return {
    parent: transform.child,
    child: transform.parent,
    x: round(-cos * transform.x - sin * transform.y, 4),
    y: round(sin * transform.x - cos * transform.y, 4),
    yaw: normalizeAngle(-transform.yaw),
    updatedAt: transform.updatedAt,
    static: transform.static
  };
}

function unavailableTf(parent, child) {
  return {
    connected: false,
    frameId: parent,
    childFrameId: child,
    source: 'tf',
    pose: { x: null, y: null, yaw: null },
    updatedAt: null,
    reason: `TF ${parent} -> ${child} is unavailable`
  };
}

function tfPose(transform, sources) {
  return {
    connected: true,
    frameId: transform.parent,
    childFrameId: transform.child,
    source: 'tf',
    pose: { x: transform.x, y: transform.y, yaw: round(transform.yaw, 4) },
    updatedAt: transform.updatedAt,
    static: transform.static,
    transforms: sources.map((source) => `${source.parent}->${source.child}`)
  };
}

function isFresh(sample, now) {
  if (!sample?.connected) return false;
  if (sample.static === true) return true;
  const updated = Date.parse(sample.updatedAt);
  const current = Date.parse(now);
  return Number.isFinite(updated) && Number.isFinite(current) && current - updated <= REALTIME_STALE_MS;
}

function oldestTimestamp(a, b) {
  const aTime = Date.parse(a);
  const bTime = Date.parse(b);
  if (!Number.isFinite(aTime)) return b ?? null;
  if (!Number.isFinite(bTime)) return a ?? null;
  return aTime <= bTime ? a : b;
}

function combinedDynamicTimestamp(first, second) {
  if (first.static && second.static) return null;
  if (first.static) return second.updatedAt ?? null;
  if (second.static) return first.updatedAt ?? null;
  return oldestTimestamp(first.updatedAt, second.updatedAt);
}

function normalizeAngle(value) {
  let angle = value;
  while (angle > Math.PI) angle -= Math.PI * 2;
  while (angle < -Math.PI) angle += Math.PI * 2;
  return round(angle, 4);
}

function quaternionYaw(q = {}) {
  const x = finite(q.x, 0);
  const y = finite(q.y, 0);
  const z = finite(q.z, 0);
  const w = finite(q.w, 1);
  const norm = Math.sqrt(x * x + y * y + z * z + w * w);
  if (!Number.isFinite(norm) || norm < 0.001) return null;
  const siny = 2 * (w * z + x * y);
  const cosy = 1 - 2 * (y * y + z * z);
  return round(Math.atan2(siny, cosy), 4);
}

function normalizeCell(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return -1;
  if (number < 0) return -1;
  return Math.max(0, Math.min(100, Math.round(number)));
}

function integer(value) {
  const number = Number(value);
  return Number.isInteger(number) && number > 0 ? number : null;
}

function finite(value, fallback = null) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function round(value, places = 3) {
  const number = finite(value);
  if (number === null) return null;
  const scale = 10 ** places;
  return Math.round(number * scale) / scale;
}
