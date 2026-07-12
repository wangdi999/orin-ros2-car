import http from 'node:http';
import { WebSocket } from 'ws';

const HOP_BY_HOP_HEADERS = new Set([
  'connection',
  'keep-alive',
  'proxy-authenticate',
  'proxy-authorization',
  'te',
  'trailer',
  'transfer-encoding',
  'upgrade'
]);

export function buildAgentTarget(config, pathname, search = '') {
  const host = config.agent.host || config.car.host;
  const port = Number(config.agent.port || 8100);
  const suffix = pathname.slice('/api/agent'.length) || '/';
  const upstreamPath = suffix === '/health' ? '/health' : `/api/v1${suffix}`;
  return {
    host,
    port,
    path: `${upstreamPath}${search}`,
    token: config.agent.token || '',
    timeoutMs: Number(config.agent.requestTimeoutMs || 20000)
  };
}

export function proxyAgentHttp(req, res, url, getConfig, addLog) {
  const target = buildAgentTarget(getConfig(), url.pathname, url.search);
  if (!target.token && target.path !== '/health') {
    writeJson(res, 503, { ok: false, error: 'Agent token is not configured' });
    return;
  }

  const headers = {};
  for (const [name, value] of Object.entries(req.headers)) {
    if (!HOP_BY_HOP_HEADERS.has(name.toLowerCase()) && value !== undefined) headers[name] = value;
  }
  headers.host = `${target.host}:${target.port}`;
  if (target.token) headers.authorization = `Bearer ${target.token}`;

  const upstream = http.request(
    {
      hostname: target.host,
      port: target.port,
      path: target.path,
      method: req.method,
      headers,
      timeout: target.timeoutMs
    },
    (upstreamRes) => {
      const responseHeaders = {};
      for (const [name, value] of Object.entries(upstreamRes.headers)) {
        if (!HOP_BY_HOP_HEADERS.has(name.toLowerCase()) && value !== undefined) {
          responseHeaders[name] = value;
        }
      }
      res.writeHead(upstreamRes.statusCode ?? 502, responseHeaders);
      upstreamRes.pipe(res);
    }
  );

  upstream.on('timeout', () => upstream.destroy(new Error('Agent request timed out')));
  upstream.on('error', (error) => {
    addLog('warn', 'agent.proxy', `Agent proxy failed: ${error.message}`);
    if (!res.headersSent) writeJson(res, 502, { ok: false, error: error.message });
    else res.end();
  });
  req.on('aborted', () => upstream.destroy());
  req.pipe(upstream);
}

export function bridgeAgentEvents(client, getConfig, addLog) {
  const config = getConfig();
  const host = config.agent.host || config.car.host;
  const port = Number(config.agent.port || 8100);
  const token = config.agent.token || '';
  if (!token) {
    client.close(1011, 'Agent token is not configured');
    return;
  }

  const upstream = new WebSocket(`ws://${host}:${port}/api/v1/events`, {
    headers: { Authorization: `Bearer ${token}` },
    handshakeTimeout: Number(config.agent.requestTimeoutMs || 20000)
  });

  upstream.on('open', () => addLog('info', 'agent.proxy', `Agent events connected to ${host}:${port}`));
  upstream.on('message', (data, isBinary) => {
    if (client.readyState === client.OPEN) client.send(data, { binary: isBinary });
  });
  upstream.on('close', (code, reason) => {
    if (client.readyState === client.OPEN) client.close(code || 1011, reason.toString());
  });
  upstream.on('error', (error) => {
    addLog('warn', 'agent.proxy', `Agent event bridge failed: ${error.message}`);
    if (client.readyState === client.OPEN) client.close(1011, 'Agent event bridge failed');
  });

  client.on('message', (data, isBinary) => {
    if (upstream.readyState === upstream.OPEN) upstream.send(data, { binary: isBinary });
  });
  client.on('close', () => upstream.close());
  client.on('error', () => upstream.close());
}

function writeJson(res, status, payload) {
  res.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    'cache-control': 'no-store'
  });
  res.end(JSON.stringify(payload));
}
