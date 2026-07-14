export const TELEMETRY_FLUSH_MS = 33;
export const TELEMETRY_MAX_BUFFERED_BYTES = 512 * 1024;
export const TELEMETRY_MAX_LOGS = 240;

export class TelemetryDelivery {
  constructor(ws, options = {}) {
    this.ws = ws;
    this.flushMs = options.flushMs ?? TELEMETRY_FLUSH_MS;
    this.maxBufferedBytes = options.maxBufferedBytes ?? TELEMETRY_MAX_BUFFERED_BYTES;
    this.schedule = options.schedule ?? setTimeout;
    this.cancel = options.cancel ?? clearTimeout;
    this.timer = null;
    this.closed = false;
    this.snapshot = null;
    this.telemetry = {};
    this.runtimePatch = {};
    this.logs = [];
  }

  sendInitialSnapshot(data) {
    if (!this.isOpen()) return false;
    return this.send({ type: 'snapshot', data });
  }

  queueSnapshot(data) {
    this.snapshot = data;
    this.scheduleFlush();
  }

  queueTelemetry(data) {
    this.telemetry = { ...this.telemetry, ...data };
    this.scheduleFlush();
  }

  queueRuntimePatch(data) {
    this.runtimePatch = mergePatch(this.runtimePatch, data);
    this.scheduleFlush();
  }

  queueLog(entry) {
    this.logs.push(entry);
    if (this.logs.length > TELEMETRY_MAX_LOGS) this.logs.splice(0, this.logs.length - TELEMETRY_MAX_LOGS);
    this.scheduleFlush();
  }

  flush() {
    this.timer = null;
    if (!this.isOpen()) return;
    if (!this.canSend()) {
      this.scheduleFlush();
      return;
    }

    if (this.snapshot) {
      if (!this.canSend()) return this.scheduleFlush();
      const data = this.snapshot;
      this.snapshot = null;
      if (!this.send({ type: 'snapshot', data })) return;
    }
    if (Object.keys(this.telemetry).length > 0) {
      if (!this.canSend()) return this.scheduleFlush();
      const data = this.telemetry;
      this.telemetry = {};
      if (!this.send({ type: 'telemetry', data })) return;
    }
    if (Object.keys(this.runtimePatch).length > 0) {
      if (!this.canSend()) return this.scheduleFlush();
      const data = this.runtimePatch;
      this.runtimePatch = {};
      if (!this.send({ type: 'runtime-patch', data })) return;
    }
    while (this.logs.length > 0 && this.canSend()) {
      if (!this.send({ type: 'log', data: this.logs.shift() })) return;
    }
    if (this.hasPending()) this.scheduleFlush();
  }

  close() {
    this.closed = true;
    if (this.timer) this.cancel(this.timer);
    this.timer = null;
    this.snapshot = null;
    this.telemetry = {};
    this.runtimePatch = {};
    this.logs = [];
  }

  hasPending() {
    return this.snapshot !== null || Object.keys(this.telemetry).length > 0
      || Object.keys(this.runtimePatch).length > 0 || this.logs.length > 0;
  }

  scheduleFlush() {
    if (this.closed || this.timer || !this.hasPending()) return;
    this.timer = this.schedule(() => this.flush(), this.flushMs);
  }

  isOpen() {
    return !this.closed && (this.ws.readyState === this.ws.OPEN || this.ws.readyState === 1);
  }

  canSend() {
    return this.isOpen() && (this.ws.bufferedAmount ?? 0) <= this.maxBufferedBytes;
  }

  send(message) {
    if (!this.isOpen()) return false;
    try {
      this.ws.send(JSON.stringify(message));
      return true;
    } catch {
      return false;
    }
  }
}

function mergePatch(previous, next) {
  const merged = { ...previous, ...next };
  for (const [key, value] of Object.entries(next ?? {})) {
    if (isPlainObject(previous?.[key]) && isPlainObject(value)) {
      merged[key] = mergePatch(previous[key], value);
    }
  }
  return merged;
}

function isPlainObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
