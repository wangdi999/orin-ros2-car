export const WORKBENCH_TABS = [
  ['mapping', '建图'],
  ['maps', '地图'],
  ['localization', '定位'],
  ['goal', '单点导航'],
  ['route', '路线与巡航']
];

export function configuredMapId(config) {
  const match = String(config?.navigation?.map ?? '').match(/^\/root\/maps\/([A-Za-z0-9_-]{1,64})\.yaml$/);
  return match?.[1] ?? null;
}

export function navigationBlockers({ config, navigation, telemetry, motionAcknowledged, route }) {
  const blockers = [];
  if (config?.navigation?.mode !== 'navigation') blockers.push('当前不是 navigation 模式');
  if (!configuredMapId(config)) blockers.push('尚未激活托管地图');
  if (!motionAcknowledged) blockers.push('尚未确认运动风险提示');
  if (navigation?.safetyState !== 'READY') blockers.push(`安全状态为 ${navigation?.safetyState ?? 'UNKNOWN'}`);
  if (telemetry && (!telemetry.pose?.connected || telemetry.pose?.stale)) blockers.push('AMCL / TF 定位尚未就绪');
  if (!['IDLE', 'SUCCEEDED', 'FAILED', 'CANCELLED', 'TIMED_OUT', 'REJECTED', undefined].includes(navigation?.goal?.state)) {
    blockers.push('已有活动目标');
  }
  if (route && !route.configured) blockers.push('路线尚未配置');
  return blockers;
}

export function emptyRoute() {
  return {
    configured: false,
    frame_id: 'map',
    home: { name: 'Home', x: null, y: null, yaw: null },
    waypoints: [1, 2, 3].map((index) => ({ name: `Waypoint ${index}`, x: null, y: null, yaw: null })),
    default_dwell_sec: 0,
    max_retries: 1,
    failure_policy: 'skip',
    loop: false
  };
}

export function previewPoint(preview, canvas, clientX, clientY) {
  if (!preview?.resolution || !canvas?.width || !canvas?.height) return null;
  const rect = canvas.getBoundingClientRect();
  const px = Math.max(0, Math.min(canvas.width - 1, (clientX - rect.left) * canvas.width / rect.width));
  const py = Math.max(0, Math.min(canvas.height - 1, (clientY - rect.top) * canvas.height / rect.height));
  const gridX = px * preview.width / canvas.width;
  const gridY = (canvas.height - py) * preview.height / canvas.height;
  const localX = gridX * preview.resolution;
  const localY = gridY * preview.resolution;
  const yaw = preview.origin?.yaw ?? 0;
  return {
    x: round((preview.origin?.x ?? 0) + Math.cos(yaw) * localX - Math.sin(yaw) * localY),
    y: round((preview.origin?.y ?? 0) + Math.sin(yaw) * localX + Math.cos(yaw) * localY)
  };
}

export function setRoutePoint(route, index, pose) {
  if (index === 0) return { ...route, home: { ...route.home, ...pose } };
  const waypoints = route.waypoints.map((point, pointIndex) => pointIndex === index - 1 ? { ...point, ...pose } : point);
  return { ...route, waypoints };
}

export function numericRoutePoint(point) {
  const numberOrNull = (value) => value == null || (typeof value === 'string' && value.trim() === '')
    ? null
    : Number(value);
  return {
    ...point,
    x: numberOrNull(point.x),
    y: numberOrNull(point.y),
    yaw: numberOrNull(point.yaw),
    ...(point.dwell_sec === '' || point.dwell_sec == null ? {} : { dwell_sec: Number(point.dwell_sec) })
  };
}

function round(value) {
  return Math.round(value * 1e4) / 1e4;
}
