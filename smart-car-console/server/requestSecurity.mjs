const LOCAL_HOSTNAMES = new Set(['127.0.0.1', 'localhost', '::1', '[::1]']);

function hostnameFromHostHeader(value) {
  try {
    return new URL(`http://${String(value ?? '')}`).hostname.toLowerCase();
  } catch {
    return '';
  }
}

function localOrigin(value) {
  try {
    const url = new URL(String(value));
    return ['http:', 'https:'].includes(url.protocol)
      && LOCAL_HOSTNAMES.has(url.hostname.toLowerCase());
  } catch {
    return false;
  }
}

export function validateLocalRequest(headers = {}) {
  const host = hostnameFromHostHeader(headers.host);
  if (!LOCAL_HOSTNAMES.has(host)) {
    return { ok: false, statusCode: 403, reason: 'Local API requires a loopback Host header' };
  }

  const origin = headers.origin;
  if (origin && !localOrigin(origin)) {
    return { ok: false, statusCode: 403, reason: 'Cross-origin access to the local control API is forbidden' };
  }

  if (String(headers['sec-fetch-site'] ?? '').toLowerCase() === 'cross-site') {
    return { ok: false, statusCode: 403, reason: 'Cross-site access to the local control API is forbidden' };
  }

  return { ok: true, statusCode: 200, reason: null };
}

export function requireJsonContentType(headers = {}) {
  const contentType = String(headers['content-type'] ?? '').split(';', 1)[0].trim().toLowerCase();
  if (contentType !== 'application/json') {
    const error = new Error('Content-Type must be application/json');
    error.statusCode = 415;
    throw error;
  }
}
