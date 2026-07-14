const MAX_PREVIEW_WIDTH = 96;
const MAX_PREVIEW_HEIGHT = 72;

export function parseCompressedImage(msg) {
  const data = binaryToBase64(msg.data);
  if (!data) {
    return {
      connected: false,
      lastError: 'Compressed image has no data'
    };
  }
  const format = String(msg.format ?? 'jpeg').toLowerCase();
  const mime = format.includes('png') ? 'image/png' : 'image/jpeg';
  return {
    connected: true,
    frameId: msg.header?.frame_id ?? null,
    previewType: 'dataUrl',
    format,
    dataUrl: `data:${mime};base64,${data}`
  };
}

export function parseImagePreview(msg, role = 'camera') {
  const width = Number(msg.width ?? 0);
  const height = Number(msg.height ?? 0);
  const encoding = String(msg.encoding ?? '').toLowerCase();
  const data = decodeBinaryData(msg.data);
  if (!data || width <= 0 || height <= 0) {
    return {
      connected: false,
      width,
      height,
      encoding,
      lastError: 'Image message is missing dimensions or data'
    };
  }

  if (role === 'depth' || encoding.includes('16uc1') || encoding.includes('32fc1')) {
    return parseScalarImage({ msg, data, width, height, encoding, role: 'depth' });
  }
  if (role === 'ir' || encoding.includes('mono')) {
    return parseScalarImage({ msg, data, width, height, encoding, role: 'ir' });
  }
  return parseColorImage({ msg, data, width, height, encoding });
}

function parseColorImage({ msg, data, width, height, encoding }) {
  const channels = encoding.includes('rgba') || encoding.includes('bgra') ? 4 : 3;
  const step = Number(msg.step ?? width * channels);
  const sample = sampling(width, height);
  const pixels = [];
  const bgr = encoding.startsWith('bgr') || encoding.startsWith('bgra');
  for (let y = 0; y < height; y += sample.stepY) {
    for (let x = 0; x < width; x += sample.stepX) {
      const offset = y * step + x * channels;
      if (offset + 2 >= data.length) continue;
      const first = data[offset];
      const second = data[offset + 1];
      const third = data[offset + 2];
      pixels.push(bgr ? [third, second, first] : [first, second, third]);
    }
  }
  return {
    connected: true,
    frameId: msg.header?.frame_id ?? null,
    previewType: 'rgbPixels',
    encoding,
    width,
    height,
    previewWidth: sample.width,
    previewHeight: sample.height,
    pixels
  };
}

function parseScalarImage({ msg, data, width, height, encoding, role }) {
  const step = Number(msg.step ?? width * scalarBytes(encoding));
  const bytes = scalarBytes(encoding);
  const littleEndian = !encoding.includes('be');
  const view = new DataView(data.buffer, data.byteOffset, data.byteLength);
  const sample = sampling(width, height);
  const values = [];
  let min = Infinity;
  let max = -Infinity;

  for (let y = 0; y < height; y += sample.stepY) {
    for (let x = 0; x < width; x += sample.stepX) {
      const offset = y * step + x * bytes;
      const value = readScalar(view, offset, encoding, littleEndian);
      if (!Number.isFinite(value)) {
        values.push(null);
        continue;
      }
      const normalized = role === 'depth' && encoding.includes('16uc1') ? value / 1000 : value;
      min = Math.min(min, normalized);
      max = Math.max(max, normalized);
      values.push(round(normalized));
    }
  }

  return {
    connected: true,
    frameId: msg.header?.frame_id ?? null,
    previewType: 'scalarPixels',
    role,
    encoding,
    width,
    height,
    previewWidth: sample.width,
    previewHeight: sample.height,
    min: Number.isFinite(min) ? round(min) : null,
    max: Number.isFinite(max) ? round(max) : null,
    values
  };
}

function sampling(width, height) {
  const stepX = Math.max(1, Math.ceil(width / MAX_PREVIEW_WIDTH));
  const stepY = Math.max(1, Math.ceil(height / MAX_PREVIEW_HEIGHT));
  return {
    stepX,
    stepY,
    width: Math.ceil(width / stepX),
    height: Math.ceil(height / stepY)
  };
}

function scalarBytes(encoding) {
  if (encoding.includes('32f')) return 4;
  if (encoding.includes('16u') || encoding.includes('mono16')) return 2;
  return 1;
}

function readScalar(view, offset, encoding, littleEndian) {
  if (offset < 0 || offset >= view.byteLength) return NaN;
  if (encoding.includes('32f')) {
    if (offset + 4 > view.byteLength) return NaN;
    return view.getFloat32(offset, littleEndian);
  }
  if (encoding.includes('16u') || encoding.includes('mono16')) {
    if (offset + 2 > view.byteLength) return NaN;
    return view.getUint16(offset, littleEndian);
  }
  return view.getUint8(offset);
}

function decodeBinaryData(data) {
  if (typeof data === 'string') return Buffer.from(data, 'base64');
  if (Array.isArray(data)) return Buffer.from(data);
  if (ArrayBuffer.isView(data)) return Buffer.from(data.buffer, data.byteOffset, data.byteLength);
  return null;
}

function binaryToBase64(data) {
  if (typeof data === 'string') return data;
  if (Array.isArray(data)) return Buffer.from(data).toString('base64');
  if (ArrayBuffer.isView(data)) return Buffer.from(data.buffer, data.byteOffset, data.byteLength).toString('base64');
  return null;
}

function round(value) {
  return Math.round(value * 1000) / 1000;
}
