import { createReadStream, existsSync } from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { WebSocketServer } from 'ws';
import { buildTwistFromDriveInput, isZeroTwist, ZERO_TWIST } from './control.mjs';
import { getConfig, loadConfig, publicConfig, saveConfig } from './config.mjs';
import { RosbridgeClient } from './rosbridge.mjs';
import { ServiceManager } from './serviceManager.mjs';
import { SshExecutor } from './ssh.mjs';
import {
  addLog,
  bus,
  clearEmergencyStop,
  markEmergencyStop,
  runtime,
  snapshot
} from './state.mjs';

const rootDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const distDir = path.join(rootDir, 'dist');
const apiPort = Number(process.env.SMART_CAR_API_PORT ?? 8787);

await loadConfig();

const rosbridge = new RosbridgeClient(getConfig);
const ssh = new SshExecutor(getConfig, addLog);
const serviceManager = new ServiceManager(ssh, rosbridge);

rosbridge.on('disconnect', () => {
  void emergencyStop('ROSBridge disconnected');
});

const server = http.createServer(async (req, res) => {
  try {
    const url = new URL(req.url, `http://${req.headers.host}`);
    if (url.pathname.startsWith('/api/')) {
      await handleApi(req, res, url);
      return;
    }
    serveStatic(req, res, url);
  } catch (error) {
    addLog('error', 'api', error.message);
    json(res, 500, { ok: false, error: error.message });
  }
});

const telemetryWss = new WebSocketServer({ noServer: true });

server.on('upgrade', (req, socket, head) => {
  const url = new URL(req.url, `http://${req.headers.host}`);
  if (url.pathname !== '/api/telemetry') {
    socket.destroy();
    return;
  }
  telemetryWss.handleUpgrade(req, socket, head, (ws) => {
    telemetryWss.emit('connection', ws, req);
  });
});

telemetryWss.on('connection', (ws) => {
  ws.send(JSON.stringify({ type: 'snapshot', data: snapshot() }));
  const onSnapshot = (data) => {
    if (ws.readyState === ws.OPEN) ws.send(JSON.stringify({ type: 'snapshot', data }));
  };
  const onLog = (entry) => {
    if (ws.readyState === ws.OPEN) ws.send(JSON.stringify({ type: 'log', data: entry }));
  };
  bus.on('snapshot', onSnapshot);
  bus.on('log', onLog);
  ws.on('close', () => {
    bus.off('snapshot', onSnapshot);
    bus.off('log', onLog);
    void emergencyStop('Telemetry WebSocket disconnected');
  });
});

server.listen(apiPort, '127.0.0.1', () => {
  addLog('info', 'api', `Smart car API listening on http://127.0.0.1:${apiPort}`);
  rosbridge.connect();
  void serviceManager.refreshStatus();
});

setInterval(() => {
  const watchdogMs = getConfig().control.watchdogMs ?? 450;
  if (!runtime.command.active || !runtime.command.lastDriveAt) return;
  if (Date.now() - runtime.command.lastDriveAt > watchdogMs) {
    void emergencyStop('Drive watchdog timeout');
  }
}, 100);

process.on('SIGINT', async () => {
  await emergencyStop('API process interrupted');
  process.exit(0);
});

async function handleApi(req, res, url) {
  if (req.method === 'GET' && url.pathname === '/api/config') {
    json(res, 200, { ok: true, config: publicConfig() });
    return;
  }
  if (req.method === 'POST' && url.pathname === '/api/config') {
    const body = await readJson(req);
    const current = getConfig();
    const next = {
      car: {
        ...current.car,
        ...body.car,
        sshPassword: body.car?.sshPassword || current.car.sshPassword
      },
      control: {
        ...current.control,
        ...body.control
      }
    };
    await saveConfig(next);
    addLog('info', 'config', `Saved connection settings for ${next.car.sshUser}@${next.car.host}`);
    rosbridge.close();
    setTimeout(() => rosbridge.connect(), 250);
    json(res, 200, { ok: true, config: publicConfig() });
    return;
  }
  if (req.method === 'GET' && url.pathname === '/api/status') {
    await serviceManager.refreshStatus();
    json(res, 200, { ok: true, config: publicConfig(), state: snapshot() });
    return;
  }
  if (req.method === 'POST' && url.pathname === '/api/services/start') {
    const result = await serviceManager.startServices();
    json(res, result.ok ? 200 : 500, { ...result, state: snapshot() });
    return;
  }
  if (req.method === 'POST' && url.pathname === '/api/services/stop') {
    await emergencyStop('Stop services requested');
    const result = await serviceManager.stopServices();
    json(res, result.ok ? 200 : 500, { ...result, state: snapshot() });
    return;
  }
  if (req.method === 'POST' && url.pathname === '/api/emergency-stop') {
    const stopped = await emergencyStop('Emergency stop requested');
    json(res, stopped ? 200 : 503, { ok: stopped, state: snapshot() });
    return;
  }
  if (req.method === 'POST' && url.pathname === '/api/drive') {
    const body = await readJson(req);
    const twist = buildTwistFromDriveInput(body, getConfig().control);
    if (isZeroTwist(twist)) {
      await emergencyStop('Joystick released');
      json(res, 200, { ok: true, twist: ZERO_TWIST, state: snapshot() });
      return;
    }
    if (!runtime.status.canDrive) {
      json(res, 409, {
        ok: false,
        error: 'Drive disabled until required devices and ROSBridge are connected',
        blockers: runtime.status.blockers,
        state: snapshot()
      });
      return;
    }
    if (!rosbridge.connected || !rosbridge.publishTwist(twist)) {
      json(res, 409, {
        ok: false,
        error: 'ROSBridge is not connected',
        state: snapshot()
      });
      return;
    }
    runtime.command.lastDriveAt = Date.now();
    runtime.command.active = true;
    runtime.command.lastTwist = twist;
    clearEmergencyStop();
    json(res, 200, { ok: true, twist, state: snapshot() });
    return;
  }
  if (req.method === 'GET' && url.pathname === '/api/video') {
    proxyVideo(req, res);
    return;
  }
  if (req.method === 'GET' && url.pathname === '/api/ai-video') {
    proxyAiVideo(req, res);
    return;
  }
  if (req.method === 'GET' && url.pathname === '/api/ai-alarms') {
    proxyAiJson(req, res, '/api/alarms');
    return;
  }
  if (req.method === 'GET' && url.pathname === '/api/ai-perf') {
    proxyAiJson(req, res, '/api/perf');
    return;
  }
  json(res, 404, { ok: false, error: 'Not found' });
}

async function emergencyStop(reason) {
  markEmergencyStop(reason);
  const sentOverRosbridge = rosbridge.emergencyStop();
  if (!sentOverRosbridge) {
    const fallbackOk = await serviceManager.emergencyStopFallback(reason);
    return fallbackOk;
  }
  addLog('warn', 'safety', reason);
  return true;
}

function proxyVideo(req, res) {
  const upstream = http.get(`http://${getConfig().car.host}:6500/video_feed`, (upstreamRes) => {
    res.writeHead(upstreamRes.statusCode ?? 200, {
      'content-type': upstreamRes.headers['content-type'] ?? 'multipart/x-mixed-replace; boundary=frame',
      'cache-control': 'no-store'
    });
    upstreamRes.pipe(res);
  });
  upstream.on('error', (error) => {
    addLog('warn', 'video', `Video proxy failed: ${error.message}`);
    if (!res.headersSent) {
      json(res, 502, { ok: false, error: error.message });
    } else {
      res.end();
    }
  });
  req.on('close', () => upstream.destroy());
}

function serveStatic(req, res, url) {
  const pathname = url.pathname === '/' ? '/index.html' : url.pathname;
  const filePath = path.join(distDir, pathname);
  if (!filePath.startsWith(distDir) || !existsSync(filePath)) {
    res.writeHead(404, { 'content-type': 'text/plain; charset=utf-8' });
    res.end('Run npm run dev for the Vite UI, or npm run build before serving statically.');
    return;
  }
  const ext = path.extname(filePath);
  const type = {
    '.html': 'text/html; charset=utf-8',
    '.js': 'text/javascript; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.svg': 'image/svg+xml'
  }[ext] ?? 'application/octet-stream';
  res.writeHead(200, { 'content-type': type });
  createReadStream(filePath).pipe(res);
}

function readJson(req) {
  return new Promise((resolve, reject) => {
    let body = '';
    req.on('data', (chunk) => {
      body += chunk.toString('utf8');
      if (body.length > 128_000) {
        reject(new Error('Request body too large'));
        req.destroy();
      }
    });
    req.on('end', () => {
      if (!body) {
        resolve({});
        return;
      }
      try {
        resolve(JSON.parse(body));
      } catch (error) {
        reject(error);
      }
    });
    req.on('error', reject);
  });
}

function json(res, statusCode, payload) {
  res.writeHead(statusCode, {
    'content-type': 'application/json; charset=utf-8',
    'cache-control': 'no-store'
  });
  res.end(JSON.stringify(payload));
}

function proxyAiVideo(req, res) {
  const url = `http://${getConfig().car.host}:6501/video_feed`;
  const upstream = http.get(url, { timeout: 10000 }, (upstreamRes) => {
    res.writeHead(upstreamRes.statusCode ?? 200, {
      'content-type': upstreamRes.headers['content-type'] ?? 'multipart/x-mixed-replace; boundary=frame',
      'cache-control': 'no-store'
    });
    upstreamRes.pipe(res);
  });
  upstream.on('error', (error) => {
    addLog('warn', 'ai-video', `AI video proxy failed: ${error.message}`);
    if (!res.headersSent) json(res, 502, { ok: false, error: error.message });
    else res.end();
  });
  req.on('close', () => upstream.destroy());
}

function proxyAiJson(req, res, path) {
  const url = `http://${getConfig().car.host}:6501${path}`;
  const upstream = http.get(url, { timeout: 10000 }, (upstreamRes) => {
    let body = '';
    upstreamRes.on('data', (chunk) => { body += chunk.toString('utf8'); });
    upstreamRes.on('end', () => {
      const status = upstreamRes.statusCode ?? 200;
      res.writeHead(status, { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' });
      res.end(body);
    });
  });
  upstream.on('timeout', () => {
    upstream.destroy();
    addLog('warn', 'ai-api', `AI API timeout: ${path}`);
    json(res, 504, { ok: false, error: 'Upstream timeout' });
  });
  upstream.on('error', (error) => {
    addLog('warn', 'ai-api', `AI API proxy failed: ${error.message}`);
    if (!res.headersSent) json(res, 502, { ok: false, error: error.message });
    else res.end();
  });
}
