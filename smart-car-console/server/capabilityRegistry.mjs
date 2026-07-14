import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { bash } from './ssh.mjs';

export const CAPABILITY_BLOCK_REASON = '未接入 `/cmd_vel` 唯一安全仲裁，网页不可启动';

const GROUPS = [
  { key: 'core', label: '核心控制' },
  { key: 'navigation', label: '地图导航' },
  { key: 'vision', label: '视觉感知' },
  { key: 'vendor', label: '厂家演示' },
  { key: 'maintenance', label: '维护诊断' }
];

export const CAPABILITY_DEFINITIONS = [
  capability('safe_base', '安全底盘', 'core', {
    packages: ['icar_navigation', 'icar_bringup'],
    executables: ['icar_bringup/Mcnamu_driver_X3'],
    nodes: ['/cmd_vel_arbiter', '/safety_manager', '/Mcnamu_driver_X3'],
    topics: ['/control/active_source', '/safety/state', '/chassis/connected', '/odom']
  }),
  capability('lidar', '二维雷达', 'core', {
    devices: ['/dev/rplidar'], packages: ['sllidar_ros2'], nodes: ['/sllidar_node'], topics: ['/scan']
  }),
  capability('imu_odometry', 'IMU / 里程计', 'core', {
    packages: ['icar_bringup'], executables: ['icar_bringup/Mcnamu_driver_X3'],
    topics: ['/imu/data_raw', '/imu/mag', '/odom', '/vel_raw']
  }),
  capability('voltage', '主电池电压', 'core', {
    packages: ['icar_bringup'], executables: ['icar_bringup/Mcnamu_driver_X3'], topics: ['/voltage']
  }),
  capability('mapping', 'Cartographer 建图', 'navigation', {
    packages: ['cartographer_ros'], nodes: ['/cartographer_node', '/occupancy_grid_node'], topics: ['/map']
  }),
  capability('localization_navigation', 'AMCL / Nav2 定位导航', 'navigation', {
    packages: ['nav2_amcl', 'nav2_planner', 'nav2_controller', 'nav2_bt_navigator', 'icar_navigation'],
    nodes: ['/amcl', '/planner_server', '/controller_server', '/bt_navigator'],
    topics: ['/amcl_pose', '/plan', '/local_plan', '/navigate_to_pose/_action/status']
  }, { allPackages: true }),
  capability('patrol_return', '巡航与返航', 'navigation', {
    packages: ['icar_navigation'], nodes: ['/patrol_manager'], topics: ['/patrol/status', '/patrol/route']
  }, { safety: 'DISPLAY_ONLY' }),
  capability('rgb_camera', 'RGB 相机', 'vision', {
    devices: ['/dev/video*'], usbIds: ['2bc5:050f', '2bc5:060f'], packages: ['astra_camera'],
    nodes: ['/astra_camera'], topics: ['/camera/color/image_raw']
  }),
  capability('depth_ir', '深度 / 红外', 'vision', {
    usbIds: ['2bc5:060f'], packages: ['astra_camera'],
    nodes: ['/astra_camera'], topics: ['/camera/depth/image_raw', '/camera/ir/image_raw']
  }),
  capability('point_cloud', '深度点云', 'vision', {
    usbIds: ['2bc5:060f'], packages: ['astra_camera'], topics: ['/camera/depth/points', '/camera/points']
  }, { runtimeAny: true }),
  capability('color_tracking', '颜色追踪', 'vision', {
    packages: ['icar_astra'], executables: ['icar_astra/colorHSV', 'icar_astra/colorTracker'],
    nodes: ['/colorHSV', '/colorTracker'],
    topics: ['/tracking/image', '/tracking_cmd_vel_shadow']
  }, { safety: 'DISPLAY_ONLY', runtimeAny: true }),
  capability('kcf_tracking', 'KCF 目标追踪', 'vision', {
    packages: ['icar_KCFTracker'], executables: ['icar_KCFTracker/KCFTracker'],
    nodes: ['/KCFTracker'],
    topics: ['/tracking/image', '/tracking_cmd_vel_shadow']
  }, { safety: 'DISPLAY_ONLY' }),
  capability('target_tracking', '目标识别与追踪', 'vision', {
    packages: ['icar_astra'], executables: ['icar_astra/findObj', 'icar_astra/trackObj'],
    nodes: ['/findObj', '/trackObj'],
    topics: ['/tracking/image', '/tracking_cmd_vel_shadow']
  }, { safety: 'DISPLAY_ONLY', runtimeAny: true }),
  capability('mediapipe', '人体姿态 / 手势 / 人脸', 'vision', {
    packages: ['icar_mediapipe'],
    executables: ['icar_mediapipe/hand', 'icar_mediapipe/pose', 'icar_mediapipe/holistic', 'icar_mediapipe/facemesh', 'icar_mediapipe/face_detection'],
    nodes: ['/hand', '/pose', '/holistic', '/facemesh', '/face_detection']
  }, { safety: 'DISPLAY_ONLY', runtimeAny: true }),
  capability('ar', 'AR 视觉', 'vision', {
    packages: ['icar_visual'], executables: ['icar_visual/AR'], nodes: ['/AR']
  }, { safety: 'DISPLAY_ONLY' }),
  capability('laser_avoidance', '激光避障演示', 'vendor', {
    packages: ['icar_laser'], executables: ['icar_laser/laser_Avoidance_a1_X3'],
    nodes: ['/laser_Avoidance_a1_X3'], topics: ['/scan']
  }, { safety: 'BLOCKED', motionDemo: true }),
  capability('laser_tracking', '激光追踪演示', 'vendor', {
    packages: ['icar_laser'], executables: ['icar_laser/laser_Tracker_a1_X3'],
    nodes: ['/laser_Tracker_a1_X3'], topics: ['/scan']
  }, { safety: 'BLOCKED', motionDemo: true }),
  capability('laser_warning', '激光告警', 'vendor', {
    packages: ['icar_laser'], executables: ['icar_laser/laser_Warning_a1_X3'],
    nodes: ['/laser_Warning_a1_X3'], topics: ['/scan']
  }, { safety: 'DISPLAY_ONLY' }),
  capability('line_follow', '巡线演示', 'vendor', {
    packages: ['icar_linefollow'], executables: ['icar_linefollow/linefollow_X3'], nodes: ['/linefollow_X3']
  }, { safety: 'BLOCKED', motionDemo: true }),
  capability('voice_control', '语音控制演示', 'vendor', {
    packages: ['icar_voice_ctrl'], executables: ['icar_voice_ctrl/voice_ctrl_X3'], nodes: ['/voice_ctrl_X3']
  }, { safety: 'BLOCKED', motionDemo: true }),
  capability('pointcloud_mapping', '点云建图', 'vendor', {
    usbIds: ['2bc5:060f'], packages: ['icar_slam'], executables: ['icar_slam/pointcloud_mapping'],
    nodes: ['/pointcloud_mapping']
  }, { safety: 'DISPLAY_ONLY' }),
  capability('chassis_calibration', 'X3 底盘标定', 'maintenance', {
    packages: ['icar_bringup'], executables: ['icar_bringup/calibration_X3'], nodes: ['/calibration_X3']
  }, { safety: 'DISPLAY_ONLY' }),
  capability('map_save', '地图保存', 'maintenance', {
    packages: ['icar_app_save_map', 'nav2_map_server', 'icar_navigation'],
    executables: ['icar_app_save_map/save_map', 'icar_navigation/save_map.sh', 'icar_navigation/verify_navigation.sh']
  }, { safety: 'DISPLAY_ONLY', packageSufficient: true })
];

function capability(key, label, group, requirements, options = {}) {
  return {
    key,
    label,
    group,
    safety: options.safety ?? 'SAFE',
    motionDemo: Boolean(options.motionDemo),
    runtimeAny: Boolean(options.runtimeAny),
    packageSufficient: Boolean(options.packageSufficient),
    allPackages: Boolean(options.allPackages),
    requirements: {
      devices: requirements.devices ?? [],
      usbIds: requirements.usbIds ?? [],
      packages: requirements.packages ?? [],
      executables: requirements.executables ?? [],
      nodes: requirements.nodes ?? [],
      topics: requirements.topics ?? []
    }
  };
}

export function evaluateCapabilities(rawEvidence = {}, previous = null, options = {}) {
  const now = options.now ?? new Date().toISOString();
  const evidence = sanitizeCapabilityEvidence(rawEvidence);
  const probeOk = evidence.probeOk === true;
  const containerStopped = evidence.ros?.containerRunning === false;
  const packagesInspectable = evidence.ros?.packagesInspectable === true;
  const items = {};

  for (const definition of CAPABILITY_DEFINITIONS) {
    const prior = previous?.items?.[definition.key] ?? null;
    const matches = matchEvidence(definition.requirements, evidence);
    const staticEvidenceRequired = definition.requirements.devices.length > 0
      || definition.requirements.usbIds.length > 0
      || definition.requirements.packages.length > 0
      || definition.requirements.executables.length > 0;
    const executableEvidenceRequired = definition.requirements.executables.length > 0
      && !definition.packageSufficient;
    const packageEvidence = definition.allPackages
      ? matchesEveryPattern(definition.requirements.packages, evidence.ros?.packages)
      : matches.packages.length > 0;
    const supportedNow = staticEvidenceRequired
      ? executableEvidenceRequired
        ? [...matches.hardware, ...matches.executables].length > 0
        : matches.hardware.length > 0 || matches.executables.length > 0 || packageEvidence
      : [...matches.nodes, ...matches.topics].length > 0;
    const domains = requirementDomains(definition.requirements);
    const definitiveMissing = probeOk
      && evidence.complete === true
      && (!domains.hardware || evidence.hardware?.complete !== false)
      && (!domains.ros || packagesInspectable)
      && !supportedNow;

    let availability = 'UNKNOWN';
    let lastConfirmedAt = prior?.lastConfirmedAt ?? null;
    if (supportedNow) {
      availability = 'SUPPORTED';
      lastConfirmedAt = evidence.detectedAt ?? now;
    } else if (definitiveMissing) {
      availability = 'UNSUPPORTED';
    } else if (['SUPPORTED', 'UNSUPPORTED'].includes(prior?.availability)) {
      availability = prior.availability;
    }

    const hasRuntimeRequirements = definition.requirements.nodes.length > 0
      || definition.requirements.topics.length > 0;
    const activeNow = hasRuntimeRequirements && (definition.runtimeAny
      ? (definition.requirements.nodes.length === 0 || matches.nodes.length > 0)
        && (definition.requirements.topics.length === 0 || matches.topics.length > 0)
      : matchesEveryPattern(definition.requirements.nodes, evidence.ros?.nodes)
        && matchesEveryPattern(definition.requirements.topics, evidence.ros?.topics));
    let runtime = 'INACTIVE';
    let reason = null;
    if (!probeOk) {
      runtime = ['SUPPORTED', 'UNSUPPORTED'].includes(prior?.availability) ? 'STALE' : 'ERROR';
      reason = ['SUPPORTED', 'UNSUPPORTED'].includes(prior?.availability)
        ? '探测失败，保留最后一次真实证据并标记过期'
        : '只读探测失败，暂无可确认的能力证据';
    } else if (containerStopped && ['SUPPORTED', 'UNSUPPORTED'].includes(availability) && !supportedNow) {
      runtime = 'STALE';
      reason = 'ROS 容器已停止，保留缓存中的已具备能力；运行证据已过期';
    } else if (activeNow) {
      runtime = 'ACTIVE';
    } else if (availability === 'UNSUPPORTED') {
      runtime = 'INACTIVE';
      reason = '新鲜、完整的只读探测未发现所需硬件或 X3 ROS 软件';
    } else if (availability === 'UNKNOWN') {
      runtime = packagesInspectable || domains.hardware ? 'INACTIVE' : 'STALE';
      reason = '证据不足，暂不能确认是否具备';
    } else {
      runtime = 'INACTIVE';
      reason = containerStopped ? '已具备，ROS 容器未运行' : '已具备，相关节点或 topic 当前未运行';
    }

    const combinedEvidence = supportedNow
      ? evidenceForItem(matches, evidence)
      : clonePublicEvidence(prior?.evidence);
    const safety = definition.motionDemo ? 'BLOCKED' : definition.safety;
    items[definition.key] = {
      key: definition.key,
      label: definition.label,
      group: definition.group,
      availability,
      runtime,
      safety,
      blockedReason: safety === 'BLOCKED' ? CAPABILITY_BLOCK_REASON : null,
      reason,
      lastConfirmedAt,
      checkedAt: evidence.detectedAt ?? now,
      evidence: combinedEvidence,
      requirements: cloneRequirements(definition.requirements)
    };
  }

  return {
    schemaVersion: 1,
    target: 'X3',
    groups: GROUPS.map((group) => ({ ...group })),
    detectedAt: evidence.detectedAt ?? now,
    stale: !probeOk || evidence.complete !== true || !packagesInspectable || Boolean(containerStopped),
    error: probeOk ? null : '只读能力探测失败；已保留最后一次非敏感证据',
    evidence: summaryEvidence(evidence),
    items
  };
}

function matchesEveryPattern(patterns = [], values = []) {
  return patterns.every((pattern) => matchPatterns([pattern], values ?? []).length > 0);
}

function matchEvidence(requirements, evidence) {
  const devicePaths = evidence.hardware?.devicePaths ?? [];
  const usbIds = evidence.hardware?.usbIds ?? [];
  const packages = evidence.ros?.packages ?? [];
  const executables = evidence.ros?.executables ?? [];
  const nodes = evidence.ros?.nodes ?? [];
  const topics = evidence.ros?.topics ?? [];
  return {
    hardware: [
      ...matchPatterns(requirements.devices, devicePaths),
      ...matchPatterns(requirements.usbIds, usbIds)
    ],
    packages: matchPatterns(requirements.packages, packages),
    executables: matchPatterns(requirements.executables, executables),
    nodes: matchPatterns(requirements.nodes, nodes),
    topics: matchPatterns(requirements.topics, topics)
  };
}

function requirementDomains(requirements) {
  return {
    hardware: requirements.devices.length > 0 || requirements.usbIds.length > 0,
    ros: requirements.packages.length > 0 || requirements.executables.length > 0
  };
}

function matchPatterns(patterns, values) {
  const result = [];
  for (const pattern of patterns) {
    const regex = wildcardRegex(pattern);
    for (const value of values) {
      if (regex.test(value) && !result.includes(value)) result.push(value);
    }
  }
  return result;
}

function wildcardRegex(pattern) {
  const escaped = String(pattern).replace(/[.+?^${}()|[\]\\]/g, '\\$&').replaceAll('*', '.*');
  return new RegExp(`^${escaped}$`, 'i');
}

function evidenceForItem(matches, evidence) {
  return {
    hardware: matches.hardware,
    packages: matches.packages,
    executables: matches.executables,
    nodes: matches.nodes,
    topics: matches.topics.map((topic) => topicEvidence(topic, evidence)),
    source: evidence.source ?? 'readonly-ssh-probe'
  };
}

function topicEvidence(topic, evidence) {
  const metric = evidence.ros?.topicMetrics?.[topic];
  if (!metric) return { topic, frequencyHz: null, ageMs: null };
  return {
    topic,
    frequencyHz: finiteOrNull(metric.frequencyHz),
    ageMs: finiteOrNull(metric.ageMs)
  };
}

function cloneRequirements(requirements) {
  return Object.fromEntries(Object.entries(requirements).map(([key, values]) => [key, [...values]]));
}

function clonePublicEvidence(evidence) {
  if (!evidence) return { hardware: [], packages: [], executables: [], nodes: [], topics: [], source: 'none' };
  return sanitizeItemEvidence(evidence);
}

function summaryEvidence(evidence) {
  return {
    source: evidence.source ?? 'readonly-ssh-probe',
    hardware: {
      devicePaths: [...(evidence.hardware?.devicePaths ?? [])],
      usbIds: [...(evidence.hardware?.usbIds ?? [])]
    },
    ros: {
      container: evidence.ros?.container ?? null,
      containerRunning: evidence.ros?.containerRunning ?? false,
      packagesInspectable: evidence.ros?.packagesInspectable ?? false,
      packageCount: evidence.ros?.packages?.length ?? 0,
      nodeCount: evidence.ros?.nodes?.length ?? 0,
      topicCount: evidence.ros?.topics?.length ?? 0
    }
  };
}

export function sanitizeCapabilityEvidence(value) {
  const source = value && typeof value === 'object' ? value : {};
  return {
    probeOk: source.probeOk === true,
    complete: source.complete === true,
    detectedAt: isoOrNull(source.detectedAt),
    source: safeText(source.source, 'readonly-ssh-probe'),
    hardware: {
      complete: source.hardware?.complete !== false,
      devicePaths: safeList(source.hardware?.devicePaths, (entry) => entry.startsWith('/dev/')),
      usbIds: safeList(source.hardware?.usbIds, (entry) => /^[0-9a-f]{4}:[0-9a-f]{4}$/i.test(entry))
    },
    ros: {
      container: safeContainer(source.ros?.container),
      containerRunning: source.ros?.containerRunning === true,
      packagesInspectable: source.ros?.packagesInspectable === true,
      packages: safeList(source.ros?.packages, safeRosName),
      executables: safeList(source.ros?.executables, safeRosPath),
      nodes: safeList(source.ros?.nodes, safeRosPath),
      topics: safeList(source.ros?.topics, safeRosPath),
      topicMetrics: sanitizeTopicMetrics(source.ros?.topicMetrics)
    }
  };
}

function sanitizeTopicMetrics(metrics) {
  if (!metrics || typeof metrics !== 'object') return {};
  const clean = {};
  for (const [topic, value] of Object.entries(metrics)) {
    if (!safeRosPath(topic) || !value || typeof value !== 'object') continue;
    clean[topic] = {
      frequencyHz: finiteOrNull(value.frequencyHz),
      ageMs: finiteOrNull(value.ageMs)
    };
  }
  return clean;
}

function safeList(values, predicate) {
  if (!Array.isArray(values)) return [];
  return [...new Set(values.map((value) => String(value).trim()).filter((value) => value && predicate(value)))].slice(0, 512);
}

function safeRosName(value) {
  return /^[A-Za-z0-9_]+$/.test(value);
}

function safeRosPath(value) {
  return /^\/?[A-Za-z0-9_./-]+$/.test(value);
}

function safeContainer(value) {
  const text = String(value ?? '').trim();
  return /^[A-Za-z0-9_.-]+$/.test(text) ? text : null;
}

function safeText(value, fallback) {
  const text = String(value ?? '').trim();
  return /^[A-Za-z0-9_.:/-]+$/.test(text) ? text : fallback;
}

function isoOrNull(value) {
  const timestamp = Date.parse(value);
  return Number.isFinite(timestamp) ? new Date(timestamp).toISOString() : null;
}

function finiteOrNull(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

export class CapabilityManager {
  constructor({ ssh, cachePath, logger = () => {}, minRefreshMs = 15000 }) {
    this.ssh = ssh;
    this.cachePath = cachePath;
    this.logger = logger;
    this.minRefreshMs = minRefreshMs;
    this.current = null;
    this.cacheLoaded = false;
    this.lastAttemptMs = 0;
    this.inflight = null;
  }

  async refresh(options = {}) {
    if (this.inflight) return this.inflight;
    this.inflight = this.refreshOnce(options);
    try {
      return await this.inflight;
    } finally {
      this.inflight = null;
    }
  }

  async refreshOnce(options = {}) {
    const now = options.now ?? new Date().toISOString();
    await this.loadCache();
    const attemptMs = Date.parse(now);
    if (!options.force && this.current && this.lastAttemptMs
      && Number.isFinite(attemptMs) && attemptMs - this.lastAttemptMs < this.minRefreshMs) {
      return this.current;
    }
    this.lastAttemptMs = Number.isFinite(attemptMs) ? attemptMs : Date.now();
    const result = await this.ssh.run(bash(buildReadonlyCapabilityProbeScript()), { timeoutMs: 20000 });
    let evidence;
    if (result.ok) {
      try {
        evidence = parseProbeOutput(result.stdout, now);
      } catch {
        evidence = failedEvidence(now);
        this.logger('warn', 'capabilities', '只读能力探测返回无法解析，保留缓存', { code: result.code ?? null });
      }
    } else {
      evidence = failedEvidence(now);
      this.logger('warn', 'capabilities', '只读能力探测失败，保留缓存', {
        code: result.code ?? null,
        timedOut: result.timedOut === true
      });
    }
    this.current = evaluateCapabilities(evidence, this.current, { now });
    await this.saveCache();
    return this.current;
  }

  get() {
    return this.current ?? evaluateCapabilities(failedEvidence(new Date().toISOString()));
  }

  async loadCache() {
    if (this.cacheLoaded) return;
    this.cacheLoaded = true;
    try {
      const parsed = JSON.parse(await readFile(this.cachePath, 'utf8'));
      if (parsed?.schemaVersion === 1 && parsed?.target === 'X3' && parsed?.items) {
        this.current = sanitizeRegistryForCache(parsed);
      }
    } catch {
      // First run and invalid caches both begin with UNKNOWN evidence.
    }
  }

  async saveCache() {
    if (!this.cachePath || !this.current) return;
    const safe = sanitizeRegistryForCache(this.current);
    await mkdir(path.dirname(this.cachePath), { recursive: true });
    await writeFile(this.cachePath, `${JSON.stringify(safe, null, 2)}\n`, 'utf8');
  }
}

function sanitizeRegistryForCache(registry) {
  const safe = {
    schemaVersion: 1,
    target: 'X3',
    groups: GROUPS.map((group) => ({ ...group })),
    detectedAt: isoOrNull(registry.detectedAt),
    stale: Boolean(registry.stale),
    error: registry.error ? '只读能力探测失败；已保留最后一次非敏感证据' : null,
    evidence: sanitizeRegistrySummary(registry.evidence),
    items: {}
  };
  for (const definition of CAPABILITY_DEFINITIONS) {
    const item = registry.items?.[definition.key];
    if (!item) continue;
    safe.items[definition.key] = {
      key: definition.key,
      label: definition.label,
      group: definition.group,
      availability: ['SUPPORTED', 'UNSUPPORTED', 'UNKNOWN'].includes(item.availability) ? item.availability : 'UNKNOWN',
      runtime: ['ACTIVE', 'INACTIVE', 'STALE', 'ERROR'].includes(item.runtime) ? item.runtime : 'ERROR',
      safety: definition.motionDemo ? 'BLOCKED' : definition.safety,
      blockedReason: definition.motionDemo ? CAPABILITY_BLOCK_REASON : null,
      reason: sanitizedRuntimeReason(item.runtime, item.availability),
      lastConfirmedAt: isoOrNull(item.lastConfirmedAt),
      checkedAt: isoOrNull(item.checkedAt),
      evidence: sanitizeItemEvidence(item.evidence),
      requirements: cloneRequirements(definition.requirements)
    };
  }
  return safe;
}

function sanitizeRegistrySummary(value) {
  return {
    source: safeText(value?.source, 'readonly-ssh-probe'),
    hardware: {
      devicePaths: safeList(value?.hardware?.devicePaths, (entry) => entry.startsWith('/dev/')),
      usbIds: safeList(value?.hardware?.usbIds, (entry) => /^[0-9a-f]{4}:[0-9a-f]{4}$/i.test(entry))
    },
    ros: {
      container: safeContainer(value?.ros?.container),
      containerRunning: value?.ros?.containerRunning === true,
      packagesInspectable: value?.ros?.packagesInspectable === true,
      packageCount: boundedCount(value?.ros?.packageCount),
      nodeCount: boundedCount(value?.ros?.nodeCount),
      topicCount: boundedCount(value?.ros?.topicCount)
    }
  };
}

function sanitizeItemEvidence(value) {
  const topics = Array.isArray(value?.topics) ? value.topics : [];
  return {
    hardware: safeList(value?.hardware, (entry) => entry.startsWith('/dev/') || /^[0-9a-f]{4}:[0-9a-f]{4}$/i.test(entry)),
    packages: safeList(value?.packages, safeRosName),
    executables: safeList(value?.executables, safeRosPath),
    nodes: safeList(value?.nodes, safeRosPath),
    topics: topics.slice(0, 512).flatMap((entry) => {
      const topic = String(entry?.topic ?? '').trim();
      if (!safeRosPath(topic)) return [];
      return [{ topic, frequencyHz: finiteOrNull(entry.frequencyHz), ageMs: finiteOrNull(entry.ageMs) }];
    }),
    source: safeText(value?.source, 'none')
  };
}

function boundedCount(value) {
  const count = Number(value);
  return Number.isInteger(count) && count >= 0 ? Math.min(count, 100000) : 0;
}

function sanitizedRuntimeReason(runtime, availability) {
  if (runtime === 'STALE') return '缓存中的最后一次可信状态；当前运行证据已过期';
  if (runtime === 'ERROR') return '只读能力探测失败';
  if (availability === 'UNSUPPORTED') return '新鲜、完整的只读探测未发现所需硬件或 X3 ROS 软件';
  if (runtime === 'INACTIVE' && availability === 'SUPPORTED') return '已具备，当前未运行';
  if (availability === 'UNKNOWN') return '证据不足，暂不能确认是否具备';
  return null;
}

function parseProbeOutput(stdout, fallbackNow) {
  const text = String(stdout ?? '').trim();
  if (!text) throw new Error('empty probe output');
  if (text.startsWith('{')) {
    return sanitizeCapabilityEvidence({ ...JSON.parse(text), probeOk: true });
  }
  const evidence = {
    probeOk: true,
    complete: false,
    detectedAt: fallbackNow,
    source: 'readonly-ssh-probe',
    hardware: { complete: true, devicePaths: [], usbIds: [] },
    ros: {
      container: null,
      containerRunning: false,
      packagesInspectable: false,
      packages: [], executables: [], nodes: [], topics: [], topicMetrics: {}
    }
  };
  for (const line of text.split(/\r?\n/)) {
    const [tag, ...parts] = line.trim().split('|');
    const value = parts.join('|').trim();
    if (tag === 'DETECTED_AT') evidence.detectedAt = value;
    if (tag === 'COMPLETE') evidence.complete = value === '1';
    if (tag === 'DEVICE') evidence.hardware.devicePaths.push(value);
    if (tag === 'USB') evidence.hardware.usbIds.push(value.toLowerCase());
    if (tag === 'CONTAINER') evidence.ros.container = value || null;
    if (tag === 'CONTAINER_RUNNING') evidence.ros.containerRunning = value === '1';
    if (tag === 'PACKAGES_INSPECTABLE') evidence.ros.packagesInspectable = value === '1';
    if (tag === 'PACKAGE') evidence.ros.packages.push(value);
    if (tag === 'EXECUTABLE') evidence.ros.executables.push(value);
    if (tag === 'NODE') evidence.ros.nodes.push(value);
    if (tag === 'TOPIC') evidence.ros.topics.push(value);
  }
  return sanitizeCapabilityEvidence(evidence);
}

function failedEvidence(now) {
  return sanitizeCapabilityEvidence({
    probeOk: false,
    complete: false,
    detectedAt: now,
    source: 'readonly-ssh-probe',
    hardware: { complete: false, devicePaths: [], usbIds: [] },
    ros: { containerRunning: false, packagesInspectable: false }
  });
}

export function buildReadonlyCapabilityProbeScript() {
  return `
set +e
echo 'SC_CAPABILITY_PROBE_V1'
echo "DETECTED_AT|$(date -u +%Y-%m-%dT%H:%M:%SZ)"
for dev in /dev/rplidar /dev/ttyUSB* /dev/ttyACM* /dev/video* /dev/AstraDepth /dev/AstraUVC /dev/astradepth /dev/astrauvc; do
  [ -e "$dev" ] && echo "DEVICE|$dev"
done
for usb in /sys/bus/usb/devices/*; do
  [ -r "$usb/idVendor" ] && [ -r "$usb/idProduct" ] || continue
  vendor="$(tr '[:upper:]' '[:lower:]' <"$usb/idVendor")"
  product="$(tr '[:upper:]' '[:lower:]' <"$usb/idProduct")"
  echo "USB|$vendor:$product"
done
cid="$(docker ps -a --filter ancestor=icar/ros-foxy:1.0.2 --format '{{.ID}}' 2>/dev/null | head -n1)"
if [ -z "$cid" ]; then
  cid="$(docker ps -a --filter name=smartcar_icar_console --format '{{.ID}}' 2>/dev/null | head -n1)"
fi
if [ -n "$cid" ]; then
  cname="$(docker inspect --format '{{.Name}}' "$cid" 2>/dev/null | sed 's#^/##')"
  echo "CONTAINER|$cname"
  running="$(docker inspect --format '{{.State.Running}}' "$cid" 2>/dev/null)"
  if [ "$running" = 'true' ]; then
    echo 'CONTAINER_RUNNING|1'
    probe_output="$(docker exec "$cid" bash -lc '
      set -o pipefail
      for setup in /opt/ros/foxy/setup.bash /root/icar_ros2_ws/icar_ws/install/setup.bash /root/icar_ros2_ws/software/library_ws/install/setup.bash /root/ros2_navigation_overlay/install/setup.bash; do
        [ -f "$setup" ] && source "$setup"
      done
      packages="$(ros2 pkg list 2>/dev/null)" || exit 21
      nodes="$(ros2 node list --no-daemon 2>/dev/null)" || exit 22
      topics="$(ros2 topic list --no-daemon 2>/dev/null)" || exit 23
      printf "%s\n" "$packages" | sed "s/^/PACKAGE|/"
      for pkg in icar_bringup icar_navigation icar_astra icar_KCFTracker icar_laser icar_linefollow icar_mediapipe icar_visual icar_voice_ctrl icar_slam icar_app_save_map; do
        ros2 pkg executables "$pkg" 2>/dev/null | while read -r package executable; do
          echo "EXECUTABLE|$package/$executable"
        done
      done
      command -v save_map.sh >/dev/null 2>&1 && echo "EXECUTABLE|icar_navigation/save_map.sh"
      command -v verify_navigation.sh >/dev/null 2>&1 && echo "EXECUTABLE|icar_navigation/verify_navigation.sh"
      printf "%s\n" "$nodes" | sed "s/^/NODE|/"
      printf "%s\n" "$topics" | sed "s/^/TOPIC|/"
    ')"
    probe_rc=$?
    if [ "$probe_rc" -eq 0 ]; then
      echo 'PACKAGES_INSPECTABLE|1'
      printf '%s\n' "$probe_output"
      echo 'COMPLETE|1'
    else
      echo 'PACKAGES_INSPECTABLE|0'
      echo 'COMPLETE|0'
    fi
  else
    echo 'CONTAINER_RUNNING|0'
    echo 'PACKAGES_INSPECTABLE|0'
    echo 'COMPLETE|0'
  fi
else
  echo 'CONTAINER_RUNNING|0'
  echo 'PACKAGES_INSPECTABLE|0'
  echo 'COMPLETE|0'
fi
`;
}
