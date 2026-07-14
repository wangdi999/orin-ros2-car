const DEFAULT_SOURCE_WIDTH = 640;
const DEFAULT_SOURCE_HEIGHT = 480;

export function parseDetectionsMessage(msg = {}, type = '') {
  if (String(type).includes('String')) return parseJsonDetections(msg.data ?? msg);
  if (Array.isArray(msg.detections)) return parseDetection2DArray(msg);
  return parseJsonDetections(msg);
}

export function parseDetection2DArray(msg = {}) {
  const detections = Array.isArray(msg.detections) ? msg.detections : [];
  return normalizeDetections(detections.map((item, index) => {
    const bbox = item.bbox ?? {};
    const center = bbox.center?.position ?? bbox.center ?? {};
    const result = bestResult(item.results);
    const width = finite(bbox.size_x ?? bbox.width);
    const height = finite(bbox.size_y ?? bbox.height);
    const centerX = finite(center.x);
    const centerY = finite(center.y);
    return {
      id: item.id ?? `${msg.header?.stamp?.sec ?? Date.now()}-${index}`,
      label: result.label,
      confidence: result.confidence,
      centerX,
      centerY,
      width,
      height,
      x: centerX === null || width === null ? null : centerX - width / 2,
      y: centerY === null || height === null ? null : centerY - height / 2
    };
  }), msg.header);
}

export function parseJsonDetections(input) {
  let payload = input;
  if (typeof input === 'string') {
    try {
      payload = JSON.parse(input);
    } catch {
      return normalizeDetections([], null, 'Detection JSON is invalid');
    }
  }
  const source = Array.isArray(payload)
    ? payload
    : payload?.detections ?? payload?.boxes ?? payload?.objects ?? [];
  const header = payload?.header ?? null;
  const image = payload?.image ?? payload?.source ?? {};
  return normalizeDetections((Array.isArray(source) ? source : []).map((item, index) => {
    const x = finite(item.x ?? item.left ?? item.xmin);
    const y = finite(item.y ?? item.top ?? item.ymin);
    const width = finite(item.width ?? item.w ?? (item.xmax !== undefined && x !== null ? Number(item.xmax) - x : null));
    const height = finite(item.height ?? item.h ?? (item.ymax !== undefined && y !== null ? Number(item.ymax) - y : null));
    return {
      id: item.id ?? `${Date.now()}-${index}`,
      label: String(item.label ?? item.class ?? item.className ?? item.name ?? item.class_id ?? 'object'),
      confidence: finite(item.confidence ?? item.score ?? item.probability, 0),
      x,
      y,
      width,
      height,
      centerX: finite(item.centerX ?? item.cx ?? (x !== null && width !== null ? x + width / 2 : null)),
      centerY: finite(item.centerY ?? item.cy ?? (y !== null && height !== null ? y + height / 2 : null))
    };
  }), header, null, {
    width: finite(image.width ?? payload?.width, DEFAULT_SOURCE_WIDTH),
    height: finite(image.height ?? payload?.height, DEFAULT_SOURCE_HEIGHT)
  });
}

function normalizeDetections(items, header = null, error = null, source = {}) {
  const sourceWidth = finite(source.width, DEFAULT_SOURCE_WIDTH);
  const sourceHeight = finite(source.height, DEFAULT_SOURCE_HEIGHT);
  const detections = items
    .map((item) => ({
      id: String(item.id ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`),
      label: String(item.label ?? 'object'),
      confidence: clamp(finite(item.confidence, 0), 0, 1),
      x: round(item.x),
      y: round(item.y),
      width: round(item.width),
      height: round(item.height),
      centerX: round(item.centerX),
      centerY: round(item.centerY)
    }))
    .filter((item) => item.x !== null && item.y !== null && item.width !== null && item.height !== null && item.width > 0 && item.height > 0)
    .slice(0, 80);

  return {
    connected: error === null,
    frameId: header?.frame_id ?? null,
    sourceWidth,
    sourceHeight,
    count: detections.length,
    detections,
    lastError: error
  };
}

function bestResult(results = []) {
  const candidates = Array.isArray(results) ? results : [];
  let best = null;
  for (const result of candidates) {
    const hypothesis = result.hypothesis ?? result;
    const confidence = finite(hypothesis.score ?? result.score ?? result.confidence, 0);
    if (!best || confidence > best.confidence) {
      best = {
        label: String(hypothesis.class_id ?? hypothesis.id ?? result.class_id ?? result.label ?? 'object'),
        confidence
      };
    }
  }
  return best ?? { label: 'object', confidence: 0 };
}

function finite(value, fallback = null) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function round(value, places = 2) {
  const number = finite(value);
  if (number === null) return null;
  const scale = 10 ** places;
  return Math.round(number * scale) / scale;
}
