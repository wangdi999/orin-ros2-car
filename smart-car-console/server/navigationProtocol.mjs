export const INITIAL_POSE_TOPIC = '/initialpose';
export const INITIAL_POSE_TYPE = 'geometry_msgs/PoseWithCovarianceStamped';
export const NAVIGATE_POSE_SERVICE = '/navigation/send_goal';
export const NAVIGATE_POSE_SERVICE_TYPE = 'car_interfaces/srv/NavigatePose';

const MAP_ID = /^[A-Za-z0-9_-]{1,64}$/;

export function normalizeMapId(value) {
  const id = String(value ?? '').trim();
  if (!MAP_ID.test(id)) {
    const error = new Error('Map name must contain 1-64 letters, numbers, underscores, or hyphens');
    error.statusCode = 400;
    error.code = 'INVALID_MAP_NAME';
    throw error;
  }
  return id;
}

export function normalizePose(value, label = 'pose') {
  const x = finite(value?.x, `${label}.x`);
  const y = finite(value?.y, `${label}.y`);
  const yaw = finite(value?.yaw, `${label}.yaw`);
  if (yaw < -Math.PI || yaw > Math.PI) throw invalid(`${label}.yaw must be within [-pi, pi]`);
  return { x, y, yaw };
}

export function buildInitialPoseMessage(value, timestampMs = Date.now()) {
  const pose = normalizePose(value, 'initialPose');
  const seconds = Math.floor(timestampMs / 1000);
  const nanoseconds = Math.floor((timestampMs - seconds * 1000) * 1e6);
  const covariance = Array(36).fill(0);
  covariance[0] = 0.25;
  covariance[7] = 0.25;
  covariance[35] = 0.0685;
  return {
    header: { stamp: { sec: seconds, nanosec: nanoseconds }, frame_id: 'map' },
    pose: {
      pose: {
        position: { x: pose.x, y: pose.y, z: 0 },
        orientation: { x: 0, y: 0, z: Math.sin(pose.yaw / 2), w: Math.cos(pose.yaw / 2) }
      },
      covariance
    }
  };
}

export function validateRoute(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw invalid('Route must be an object');
  const required = ['configured', 'frame_id', 'home', 'waypoints', 'default_dwell_sec', 'max_retries', 'failure_policy', 'loop'];
  const keys = Object.keys(value);
  if (required.some((key) => !keys.includes(key)) || keys.some((key) => !required.includes(key))) {
    throw invalid('Route fields do not match the fixed route contract');
  }
  if (typeof value.configured !== 'boolean') throw invalid('configured must be boolean');
  if (value.frame_id !== 'map') throw invalid('frame_id must be map');
  if (!Array.isArray(value.waypoints) || value.waypoints.length !== 3) {
    throw invalid('Route must contain exactly three waypoints');
  }
  const defaultDwell = nonnegative(value.default_dwell_sec, 'default_dwell_sec');
  if (!Number.isInteger(value.max_retries) || value.max_retries < 0 || value.max_retries > 3) {
    throw invalid('max_retries must be an integer between 0 and 3');
  }
  if (!['skip', 'abort'].includes(value.failure_policy)) throw invalid('failure_policy must be skip or abort');
  if (typeof value.loop !== 'boolean') throw invalid('loop must be boolean');
  const home = validateWaypoint(value.home, value.configured, 'home');
  const waypoints = value.waypoints.map((item, index) => validateWaypoint(item, value.configured, `waypoints[${index}]`));
  const names = [home.name, ...waypoints.map((item) => item.name)];
  if (new Set(names).size !== names.length) throw invalid('Home and waypoint names must be unique');
  return {
    configured: value.configured,
    frame_id: 'map',
    home,
    waypoints,
    default_dwell_sec: defaultDwell,
    max_retries: value.max_retries,
    failure_policy: value.failure_policy,
    loop: value.loop
  };
}

export function serializeRouteYaml(routeValue) {
  const route = validateRoute(routeValue);
  const waypointLines = route.waypoints.map((point) => [
    `  - name: ${yamlString(point.name)}`,
    `    x: ${yamlNumber(point.x)}`,
    `    y: ${yamlNumber(point.y)}`,
    `    yaw: ${yamlNumber(point.yaw)}`,
    ...(point.dwell_sec == null ? [] : [`    dwell_sec: ${point.dwell_sec}`])
  ].join('\n')).join('\n');
  return [
    `configured: ${route.configured}`,
    'frame_id: map',
    'home:',
    `  name: ${yamlString(route.home.name)}`,
    `  x: ${yamlNumber(route.home.x)}`,
    `  y: ${yamlNumber(route.home.y)}`,
    `  yaw: ${yamlNumber(route.home.yaw)}`,
    ...(route.home.dwell_sec == null ? [] : [`  dwell_sec: ${route.home.dwell_sec}`]),
    'waypoints:',
    waypointLines,
    `default_dwell_sec: ${route.default_dwell_sec}`,
    `max_retries: ${route.max_retries}`,
    `failure_policy: ${route.failure_policy}`,
    `loop: ${route.loop}`,
    ''
  ].join('\n');
}

export function worldFromCanvas({ clientX, clientY, rect, projection }) {
  return {
    x: round((clientX - rect.left - projection.offsetX) / projection.scale),
    y: round((projection.offsetY - (clientY - rect.top)) / projection.scale)
  };
}

export function canvasToMapPoint(map, projection, canvasX, canvasY) {
  if (!map?.resolution || !projection?.cell) throw invalid('Map projection is unavailable');
  const mx = (canvasX - projection.offsetX) / projection.cell;
  const my = projection.gridH - 1 - ((canvasY - projection.offsetY) / projection.cell);
  const scale = map.resolution * (map.step || 1);
  const localX = mx * scale;
  const localY = my * scale;
  const yaw = map.origin?.yaw ?? 0;
  return {
    x: round((map.origin?.x ?? 0) + Math.cos(yaw) * localX - Math.sin(yaw) * localY),
    y: round((map.origin?.y ?? 0) + Math.sin(yaw) * localX + Math.cos(yaw) * localY)
  };
}

function validateWaypoint(value, configured, label) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw invalid(`${label} must be an object`);
  const allowed = ['name', 'x', 'y', 'yaw', 'dwell_sec'];
  if (Object.keys(value).some((key) => !allowed.includes(key))) throw invalid(`${label} has unsupported fields`);
  const name = String(value.name ?? '').trim();
  if (!name) throw invalid(`${label}.name must be non-empty`);
  const coordinates = ['x', 'y', 'yaw'].map((key) => {
    if (value[key] == null && !configured) return null;
    return finite(value[key], `${label}.${key}`);
  });
  if (coordinates[2] != null && (coordinates[2] < -Math.PI || coordinates[2] > Math.PI)) {
    throw invalid(`${label}.yaw must be within [-pi, pi]`);
  }
  return {
    name,
    x: coordinates[0],
    y: coordinates[1],
    yaw: coordinates[2],
    ...(value.dwell_sec == null ? {} : { dwell_sec: nonnegative(value.dwell_sec, `${label}.dwell_sec`) })
  };
}

function yamlString(value) {
  return JSON.stringify(String(value));
}

function yamlNumber(value) {
  return value == null ? 'null' : String(value);
}

function finite(value, label) {
  if (value == null || (typeof value === 'string' && value.trim() === '')) {
    throw invalid(`${label} must be finite`);
  }
  const number = Number(value);
  if (!Number.isFinite(number)) throw invalid(`${label} must be finite`);
  return number;
}

function nonnegative(value, label) {
  const number = finite(value, label);
  if (number < 0) throw invalid(`${label} must be non-negative`);
  return number;
}

function invalid(message) {
  const error = new Error(message);
  error.statusCode = 400;
  error.code = 'INVALID_NAVIGATION_INPUT';
  return error;
}

function round(value) {
  return Math.round(value * 1e6) / 1e6;
}
