import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { runtime, telemetry, updateAlarms } from './state.mjs';

const MAX_ALARMS = 500;
const DEFAULT_NEAR_RANGE_M = 0.35;
const LOW_VOLTAGE_WARN = 10.8;
const LOW_VOLTAGE_CRITICAL = 10.2;

export class AlarmManager {
  constructor(storagePath) {
    this.storagePath = storagePath;
    this.loaded = false;
    this.persistTimer = null;
  }

  async load() {
    if (this.loaded) return runtime.alarms;
    this.loaded = true;
    try {
      const text = await readFile(this.storagePath, 'utf8');
      const parsed = JSON.parse(text);
      updateAlarms(normalizeStore(parsed));
    } catch {
      updateAlarms({ items: [], updatedAt: new Date().toISOString() });
    }
    return runtime.alarms;
  }

  list(filters = {}) {
    let items = runtime.alarms.items ?? [];
    if (filters.status) items = items.filter((item) => item.status === filters.status);
    if (filters.severity) items = items.filter((item) => item.severity === filters.severity);
    return {
      ...runtime.alarms,
      items
    };
  }

  raise(input = {}) {
    const now = new Date().toISOString();
    const dedupeKey = String(input.dedupeKey ?? `${input.source ?? 'system'}:${input.type ?? input.title ?? 'alarm'}`);
    const items = [...(runtime.alarms.items ?? [])];
    const existing = items.find((item) => item.dedupeKey === dedupeKey && item.status !== 'resolved');
    if (existing) {
      existing.lastSeenAt = now;
      existing.count = (existing.count ?? 1) + 1;
      existing.message = input.message ?? existing.message;
      existing.severity = normalizeSeverity(input.severity ?? existing.severity);
      this.commit(items);
      return existing;
    }

    const alarm = {
      id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
      dedupeKey,
      source: String(input.source ?? 'system'),
      type: String(input.type ?? 'event'),
      severity: normalizeSeverity(input.severity),
      status: 'active',
      title: String(input.title ?? 'Alarm'),
      message: String(input.message ?? ''),
      createdAt: now,
      lastSeenAt: now,
      acknowledgedAt: null,
      resolvedAt: null,
      count: 1,
      detail: input.detail ?? null
    };
    items.unshift(alarm);
    this.commit(items.slice(0, MAX_ALARMS));
    return alarm;
  }

  ack(id) {
    return this.transition(id, 'acknowledged', 'acknowledgedAt');
  }

  resolve(id) {
    return this.transition(id, 'resolved', 'resolvedAt');
  }

  ingestCarAlarm(msg = {}) {
    if (typeof msg === 'string') {
      return this.raise({
        source: 'car',
        type: 'car_alarm',
        severity: 'warning',
        title: '车端报警',
        message: msg,
        dedupeKey: `car:${msg}`
      });
    }
    const dedupeKey = msg.dedupeKey ?? `car:${msg.type ?? msg.title ?? msg.message ?? 'alarm'}`;
    if (msg.active === false) {
      const existing = (runtime.alarms.items ?? []).find(
        (item) => item.dedupeKey === dedupeKey && item.status !== 'resolved'
      );
      return existing ? this.transition(existing.id, 'resolved', 'resolvedAt') : null;
    }
    return this.raise({
      source: msg.source ?? 'car',
      type: msg.type ?? 'car_alarm',
      severity: msg.severity ?? 'warning',
      title: msg.title ?? '车端报警',
      message: msg.message ?? JSON.stringify(msg),
      detail: msg,
      dedupeKey
    });
  }

  evaluate() {
    const status = runtime.status;
    const rosbridge = runtime.rosbridge;
    if (runtime.safety.emergencyStopActive) {
      this.raise({
        source: 'safety',
        type: 'emergency_stop',
        severity: 'critical',
        title: '急停已触发',
        message: runtime.safety.lastStopReason ?? 'Emergency stop active',
        dedupeKey: 'safety:emergency_stop'
      });
    }
    if (rosbridge.url && !rosbridge.connected) {
      this.raise({
        source: 'rosbridge',
        type: 'disconnect',
        severity: 'warning',
        title: 'ROSBridge 断开',
        message: rosbridge.lastError ?? '等待重连',
        dedupeKey: 'rosbridge:disconnect'
      });
    }
    for (const blocker of status.blockers ?? []) {
      this.raise({
        source: 'device',
        type: 'drive_blocker',
        severity: 'warning',
        title: '遥控条件未满足',
        message: blocker,
        dedupeKey: `blocker:${blocker}`
      });
    }
    this.evaluateVoltage();
    this.evaluateLidar();
    this.evaluateDetections();
  }

  evaluateVoltage() {
    const battery = Number(telemetry.voltage?.battery);
    if (!Number.isFinite(battery)) return;
    if (battery <= LOW_VOLTAGE_CRITICAL) {
      this.raise({
        source: 'voltage',
        type: 'low_voltage',
        severity: 'critical',
        title: '主车电压过低',
        message: `${battery.toFixed(2)} V`,
        dedupeKey: 'voltage:low'
      });
    } else if (battery <= LOW_VOLTAGE_WARN) {
      this.raise({
        source: 'voltage',
        type: 'low_voltage',
        severity: 'warning',
        title: '主车电压偏低',
        message: `${battery.toFixed(2)} V`,
        dedupeKey: 'voltage:low'
      });
    }
  }

  evaluateLidar() {
    const points = telemetry.lidar?.points ?? [];
    let nearest = Infinity;
    for (const point of points) {
      const range = Number(point.range);
      if (Number.isFinite(range)) nearest = Math.min(nearest, range);
    }
    if (nearest < DEFAULT_NEAR_RANGE_M) {
      this.raise({
        source: 'lidar',
        type: 'near_obstacle',
        severity: 'warning',
        title: '雷达近距报警',
        message: `最近障碍 ${nearest.toFixed(2)} m`,
        dedupeKey: 'lidar:near_obstacle'
      });
    }
  }

  evaluateDetections() {
    const detections = telemetry.detections?.detections ?? [];
    for (const item of detections) {
      if ((item.confidence ?? 0) < 0.75) continue;
      this.raise({
        source: 'vision',
        type: 'detection',
        severity: 'info',
        title: '真实目标检测事件',
        message: `${item.label} ${(item.confidence * 100).toFixed(0)}%`,
        dedupeKey: `vision:${item.label}`
      });
    }
  }

  transition(id, status, timestampField) {
    const now = new Date().toISOString();
    const items = [...(runtime.alarms.items ?? [])];
    const alarm = items.find((item) => item.id === id);
    if (!alarm) return null;
    alarm.status = status;
    alarm[timestampField] = now;
    this.commit(items);
    return alarm;
  }

  commit(items) {
    const summary = summarize(items);
    updateAlarms({
      items,
      summary,
      updatedAt: new Date().toISOString()
    });
    this.schedulePersist();
  }

  schedulePersist() {
    clearTimeout(this.persistTimer);
    this.persistTimer = setTimeout(() => {
      this.persistTimer = null;
      void this.persist();
    }, 150);
  }

  async persist() {
    await mkdir(path.dirname(this.storagePath), { recursive: true });
    await writeFile(this.storagePath, `${JSON.stringify(runtime.alarms, null, 2)}\n`, 'utf8');
  }
}

function normalizeStore(store = {}) {
  const items = Array.isArray(store.items) ? store.items.map(normalizeAlarm).filter(Boolean) : [];
  return {
    items,
    summary: summarize(items),
    updatedAt: store.updatedAt ?? new Date().toISOString()
  };
}

function normalizeAlarm(item) {
  if (!item?.id) return null;
  return {
    ...item,
    severity: normalizeSeverity(item.severity),
    status: ['active', 'acknowledged', 'resolved'].includes(item.status) ? item.status : 'active',
    count: Number.isFinite(Number(item.count)) ? Number(item.count) : 1
  };
}

function normalizeSeverity(value = 'info') {
  return ['critical', 'error', 'warning', 'info'].includes(value) ? value : 'info';
}

function summarize(items = []) {
  return {
    total: items.length,
    active: items.filter((item) => item.status === 'active').length,
    acknowledged: items.filter((item) => item.status === 'acknowledged').length,
    resolved: items.filter((item) => item.status === 'resolved').length,
    critical: items.filter((item) => item.severity === 'critical' && item.status !== 'resolved').length,
    warning: items.filter((item) => ['warning', 'error'].includes(item.severity) && item.status !== 'resolved').length
  };
}
