const TYPE_ALIASES = new Map([
  ['sensor_msgs/Image', 'sensor_msgs/msg/Image'],
  ['sensor_msgs/CompressedImage', 'sensor_msgs/msg/CompressedImage'],
  ['sensor_msgs/CameraInfo', 'sensor_msgs/msg/CameraInfo'],
  ['sensor_msgs/PointCloud2', 'sensor_msgs/msg/PointCloud2'],
  ['geometry_msgs/Twist', 'geometry_msgs/msg/Twist'],
  ['vision_msgs/Detection2DArray', 'vision_msgs/msg/Detection2DArray'],
  ['std_msgs/String', 'std_msgs/msg/String']
]);

const ROLE_DEFINITIONS = [
  {
    role: 'camera',
    label: 'RGB 图像',
    types: ['sensor_msgs/msg/CompressedImage', 'sensor_msgs/msg/Image'],
    includes: ['color', 'rgb', 'image_raw', 'image/compressed'],
    excludes: ['depth', 'ir', 'infra', 'hsv', 'mask', 'tracking', 'tracker']
  },
  {
    role: 'depth',
    label: '深度图像',
    types: ['sensor_msgs/msg/Image', 'sensor_msgs/msg/CompressedImage'],
    includes: ['depth'],
    excludes: ['points']
  },
  {
    role: 'ir',
    label: '红外图像',
    types: ['sensor_msgs/msg/Image', 'sensor_msgs/msg/CompressedImage'],
    includes: ['ir', 'infra']
  },
  {
    role: 'pointCloud',
    label: '点云',
    types: ['sensor_msgs/msg/PointCloud2'],
    includes: ['points', 'cloud', 'pointcloud']
  },
  {
    role: 'cameraInfo',
    label: '相机标定',
    types: ['sensor_msgs/msg/CameraInfo'],
    includes: ['camera_info']
  },
  {
    role: 'trackingImage',
    label: '追踪图像',
    types: ['sensor_msgs/msg/Image', 'sensor_msgs/msg/CompressedImage'],
    includes: ['hsv', 'mask', 'tracking', 'tracker', 'result']
  },
  {
    role: 'trackingVelocity',
    label: '追踪影子速度',
    types: ['geometry_msgs/msg/Twist'],
    exact: ['/tracking_cmd_vel_shadow']
  },
  {
    role: 'detections',
    label: '真实目标检测结果',
    types: ['vision_msgs/msg/Detection2DArray', 'std_msgs/msg/String'],
    includes: ['detection', 'detections', 'yolo', 'objects', 'boxes'],
    exact: ['/detections', '/yolo/detections', '/camera/detections']
  }
];

export function normalizeTopicType(type) {
  const trimmed = String(type ?? '').trim();
  if (!trimmed) return null;
  if (TYPE_ALIASES.has(trimmed)) return TYPE_ALIASES.get(trimmed);
  if (trimmed.includes('/msg/')) return trimmed;
  const parts = trimmed.split('/').filter(Boolean);
  if (parts.length === 2) return `${parts[0]}/msg/${parts[1]}`;
  return trimmed;
}

export function parseTopicListTypes(text) {
  const topics = [];
  for (const rawLine of String(text ?? '').split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line) continue;
    const bracketMatch = line.match(/^(\S+)\s+\[(.+)]$/);
    const colonMatch = line.match(/^(\S+):\s*(\S+)$/);
    const plainMatch = line.match(/^(\S+)\s+(\S+)$/);
    const topic = bracketMatch?.[1] ?? colonMatch?.[1] ?? plainMatch?.[1];
    const type = bracketMatch?.[2] ?? colonMatch?.[2] ?? plainMatch?.[2];
    if (!topic || !type) continue;
    topics.push({
      topic,
      type: normalizeTopicType(type)
    });
  }
  return topics;
}

export function discoverPerceptionTopics(topicEntries, previous = {}) {
  const entries = topicEntries.map((entry) => ({
    topic: entry.topic,
    type: normalizeTopicType(entry.type)
  }));
  const matches = {};

  for (const definition of ROLE_DEFINITIONS) {
    const match = selectRoleTopic(entries, definition);
    matches[definition.role] = {
      role: definition.role,
      label: definition.label,
      topic: match?.topic ?? previous?.matches?.[definition.role]?.topic ?? null,
      type: match?.type ?? previous?.matches?.[definition.role]?.type ?? null,
      matched: Boolean(match),
      lastError: match ? null : `No ${definition.label} topic discovered`
    };
  }

  return {
    discoveredAt: new Date().toISOString(),
    topics: entries,
    matches
  };
}

export function rosbridgeType(type) {
  const normalized = normalizeTopicType(type);
  if (!normalized) return null;
  return normalized.replace('/msg/', '/');
}

function selectRoleTopic(entries, definition) {
  const candidates = entries.filter((entry) => {
    if (!definition.types.includes(entry.type)) return false;
    if (definition.exact?.length) return definition.exact.includes(entry.topic);
    const lower = entry.topic.toLowerCase();
    if (definition.excludes?.some((part) => lower.includes(part))) return false;
    if (!definition.includes?.length) return true;
    return definition.includes.some((part) => lower.includes(part));
  });
  if (candidates.length === 0) return null;
  return candidates.toSorted((a, b) => scoreTopic(b.topic, definition) - scoreTopic(a.topic, definition))[0];
}

function scoreTopic(topic, definition) {
  const lower = topic.toLowerCase();
  let score = 0;
  for (const part of definition.includes ?? []) {
    if (lower.includes(part)) score += 2;
  }
  if (lower.includes('compressed')) score += definition.role === 'pointCloud' ? 0 : 3;
  if (lower.includes('raw')) score += 1;
  if (lower.startsWith('/camera')) score += 1;
  if (lower.startsWith('/astra')) score += 1;
  return score;
}
