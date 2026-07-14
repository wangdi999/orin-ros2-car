import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { keyboardVectorFromCodes, isDriveKeyCode } from './keyboardDrive.js';

const emptyState = {
  runtime: {
    rosbridge: { connected: false, url: null, lastError: null },
    status: {
      ssh: { connected: false, hostname: null },
      devices: {
        chassisSerial: false,
        lidar: false,
        cameraDepth: false,
        cameraUvc: false,
        video0: false
      },
      ports: { control6000: false, video6500: false, rosbridge9090: false },
      services: {
        docker: false,
        container: null,
        chassis: false,
        lidar: false,
        camera: false,
        rosbridge: false,
        video: false
      },
      canDrive: false,
      blockers: ['等待状态检查'],
      updatedAt: null
    },
    logs: [],
    safety: { emergencyStopActive: false, lastStopReason: null },
    command: { active: false, lastTwist: null }
  },
  telemetry: {
    lidar: { connected: false, rangeMax: 12, points: [] },
    imu: {
      connected: false,
      orientation: { yaw: null, roll: null, pitch: null },
      acceleration: { x: null, y: null, z: null },
      gyro: { x: null, y: null, z: null },
      magnetometer: { x: null, y: null, z: null }
    },
    voltage: { connected: false, battery: null, current: null, power: null, percent: null },
    accessoryPower: {
      connected: false,
      reason: '未发现附属设备独立电量数据源',
      devices: []
    },
    encoders: {
      connected: false,
      leftTicks: null,
      rightTicks: null,
      deltaTicks: null,
      leftRadPerSec: null,
      rightRadPerSec: null
    },
    velocity: { connected: false, linear: null, angular: null },
    environment: {
      connected: false,
      reason: '未发现小车端环境传感器数据源',
      temperature: null,
      humidity: null,
      pressure: null,
      airQuality: null,
      ambientLight: null,
      soundLevel: null
    }
  }
};

const defaultConfig = {
  car: {
    host: import.meta.env?.VITE_SMART_CAR_HOST || '',
    sshUser: 'jetson',
    sshPasswordSet: false,
    sshHostKey: '',
    plinkPath: 'D:\\putty\\plink.exe'
  },
  control: {
    maxLinearMps: 0.35,
    maxAngularRps: 1.2,
    deadZone: 0.05,
    watchdogMs: 450
  }
};

export default function App() {
  const [state, setState] = useState(emptyState);
  const [config, setConfig] = useState(defaultConfig);
  const [connection, setConnection] = useState('connecting');
  const [busy, setBusy] = useState(null);
  const [configOpen, setConfigOpen] = useState(false);
  const [linearLimit, setLinearLimit] = useState(0.18);
  const [angularLimit, setAngularLimit] = useState(0.7);
  const [driveVector, setDriveVector] = useState({ forward: 0, turn: 0, strafe: 0 });
  const [keyboardActive, setKeyboardActive] = useState(false);
  const sendDriveRef = useRef({ lastSent: 0, pending: null });
  const pressedKeysRef = useRef(new Set());

  const status = state.runtime.status;
  const telemetry = state.telemetry;
  const logs = state.runtime.logs;
  const canDrive = status.canDrive && connection === 'connected' && !busy;

  const refreshStatus = useCallback(async () => {
    const response = await fetch('/api/status', { cache: 'no-store' });
    const payload = await response.json();
    if (payload.config) setConfig(payload.config);
    if (payload.state) setState(payload.state);
  }, []);

  useEffect(() => {
    let closed = false;
    refreshStatus().catch(() => setConnection('offline'));
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const port = window.location.port === '5173' ? '8787' : window.location.port;
    const ws = new WebSocket(`${protocol}//${window.location.hostname}:${port}/api/telemetry`);
    ws.onopen = () => setConnection('connected');
    ws.onclose = () => {
      if (!closed) setConnection('offline');
    };
    ws.onerror = () => setConnection('offline');
    ws.onmessage = (event) => {
      const message = JSON.parse(event.data);
      if (message.type === 'snapshot') setState(message.data);
    };
    const poll = setInterval(() => {
      refreshStatus().catch(() => setConnection('offline'));
    }, 6000);
    return () => {
      closed = true;
      clearInterval(poll);
      ws.close();
    };
  }, [refreshStatus]);

  useEffect(() => {
    const stop = () => {
      navigator.sendBeacon('/api/emergency-stop', new Blob(['{}'], { type: 'application/json' }));
    };
    window.addEventListener('blur', stop);
    window.addEventListener('beforeunload', stop);
    return () => {
      window.removeEventListener('blur', stop);
      window.removeEventListener('beforeunload', stop);
    };
  }, []);

  const postAction = useCallback(async (path, label) => {
    setBusy(label);
    try {
      const response = await fetch(path, { method: 'POST' });
      const payload = await response.json();
      if (payload.state) setState(payload.state);
      await refreshStatus();
      return payload;
    } finally {
      setBusy(null);
    }
  }, [refreshStatus]);

  const sendDrive = useCallback((input, immediate = false) => {
    const now = performance.now();
    const next = {
      ...input,
      linearLimit,
      angularLimit
    };
    sendDriveRef.current.pending = next;
    const delay = immediate ? 0 : Math.max(0, 115 - (now - sendDriveRef.current.lastSent));
    if (sendDriveRef.current.timer) return;
    sendDriveRef.current.timer = setTimeout(async () => {
      const payload = sendDriveRef.current.pending;
      sendDriveRef.current.timer = null;
      sendDriveRef.current.lastSent = performance.now();
      try {
        const response = await fetch('/api/drive', {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify(payload)
        });
        const body = await response.json();
        if (body.state) setState(body.state);
      } catch {
        setConnection('offline');
      }
    }, delay);
  }, [angularLimit, linearLimit]);

  const stopDrive = useCallback(() => {
    setDriveVector({ forward: 0, turn: 0, strafe: 0 });
    setKeyboardActive(false);
    sendDrive({ forward: 0, turn: 0, strafe: 0 }, true);
  }, [sendDrive]);

  const sendKeyboardVector = useCallback((immediate = false) => {
    const vector = keyboardVectorFromCodes(pressedKeysRef.current);
    const hasMotion = vector.forward !== 0 || vector.turn !== 0 || vector.strafe !== 0;
    if (!canDrive) {
      setKeyboardActive(false);
      setDriveVector({ forward: 0, turn: 0, strafe: 0 });
      return;
    }
    setKeyboardActive(hasMotion);
    setDriveVector(vector);
    if (!hasMotion) {
      sendDrive({ forward: 0, turn: 0, strafe: 0 }, true);
      return;
    }
    sendDrive(vector, immediate);
  }, [canDrive, sendDrive]);

  useEffect(() => {
    if (!keyboardActive || !canDrive || configOpen) return undefined;
    const interval = setInterval(() => sendKeyboardVector(), 120);
    return () => clearInterval(interval);
  }, [canDrive, configOpen, keyboardActive, sendKeyboardVector]);

  useEffect(() => {
    function isEditableTarget(target) {
      return target?.closest?.('input, textarea, select, [contenteditable="true"]');
    }
    function resetKeys() {
      if (pressedKeysRef.current.size > 0) {
        pressedKeysRef.current.clear();
        stopDrive();
      }
    }
    async function handleKeyDown(event) {
      if (isEditableTarget(event.target) || configOpen) return;
      if (event.code === 'Space') {
        event.preventDefault();
        if (!event.repeat) {
          pressedKeysRef.current.clear();
          stopDrive();
          await postAction('/api/emergency-stop', 'stop');
        }
        return;
      }
      if (!isDriveKeyCode(event.code)) return;
      event.preventDefault();
      const before = pressedKeysRef.current.size;
      pressedKeysRef.current.add(event.code);
      if (pressedKeysRef.current.size !== before || event.repeat) {
        sendKeyboardVector(true);
      }
    }
    function handleKeyUp(event) {
      if (!isDriveKeyCode(event.code)) return;
      event.preventDefault();
      pressedKeysRef.current.delete(event.code);
      sendKeyboardVector(true);
    }

    window.addEventListener('keydown', handleKeyDown);
    window.addEventListener('keyup', handleKeyUp);
    window.addEventListener('blur', resetKeys);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
      window.removeEventListener('keyup', handleKeyUp);
      window.removeEventListener('blur', resetKeys);
    };
  }, [configOpen, postAction, sendKeyboardVector, stopDrive]);

  const topMetrics = useMemo(() => ([
    { label: '小车 IP', value: config.car.host, tone: 'teal' },
    { label: 'SSH', value: status.ssh.connected ? '已连接' : '离线', tone: status.ssh.connected ? 'green' : 'red' },
    { label: 'Docker', value: status.services.docker ? '运行中' : '已停止', tone: status.services.docker ? 'green' : 'amber' },
    { label: 'ROSBridge', value: state.runtime.rosbridge.connected ? '已连接' : '未连接', tone: state.runtime.rosbridge.connected ? 'green' : 'red' },
    { label: '摄像头', value: status.ports.video6500 ? '视频就绪' : '无视频流', tone: status.ports.video6500 ? 'green' : 'amber' },
    { label: '主车电量', value: formatBatterySummary(telemetry.voltage), tone: telemetry.voltage.connected ? 'green' : 'muted' }
  ]), [config.car.host, state.runtime.rosbridge.connected, status, telemetry.voltage]);

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <Icon name="car" />
          <span>智能小车控制台</span>
        </div>
        <div className="top-metrics">
          {topMetrics.map((metric) => (
            <StatusMetric key={metric.label} {...metric} />
          ))}
        </div>
        <div className="top-actions">
          <button className="icon-button danger" onClick={() => postAction('/api/emergency-stop', 'stop')} title="急停">
            <Icon name="stop" />
          </button>
          <button className="icon-button" onClick={() => setConfigOpen(true)} title="连接设置">
            <Icon name="settings" />
          </button>
        </div>
      </header>

      <main className="workbench">
        <NavigationRail />
        <ServicePanel status={status} rosbridge={state.runtime.rosbridge} telemetry={telemetry} />
        <section className="center-zone">
          <div className="visual-grid">
            <CameraPanel host={config.car.host} videoReady={status.ports.video6500} />
            <LidarPanel lidar={telemetry.lidar} />
          </div>
          <div className="control-grid">
            <Joystick
              disabled={!canDrive}
              vector={driveVector}
              keyboardActive={keyboardActive}
              onVector={(vector) => {
                pressedKeysRef.current.clear();
                setKeyboardActive(false);
                setDriveVector(vector);
                sendDrive(vector);
              }}
              onStop={stopDrive}
            />
            <SpeedPanel
              linearLimit={linearLimit}
              angularLimit={angularLimit}
              maxLinear={config.control.maxLinearMps}
              maxAngular={config.control.maxAngularRps}
              setLinearLimit={setLinearLimit}
              setAngularLimit={setAngularLimit}
              onEmergency={() => postAction('/api/emergency-stop', 'stop')}
              disabled={!canDrive}
            />
            <ServiceActions
              busy={busy}
              onStart={() => postAction('/api/services/start', 'start')}
              onStop={() => postAction('/api/services/stop', 'stop')}
              onRefresh={refreshStatus}
            />
          </div>
          <LogConsole logs={logs} />
        </section>
        <SensorInspector telemetry={telemetry} status={status} blockers={status.blockers} />
      </main>

      {configOpen && (
        <ConfigDialog
          config={config}
          onClose={() => setConfigOpen(false)}
          onSaved={(next) => setConfig(next)}
        />
      )}
    </div>
  );
}

function StatusMetric({ label, value, tone }) {
  return (
    <div className="status-metric">
      <span>{label}</span>
      <strong className={`tone-${tone}`}>
        <i />
        {value ?? '未连接'}
      </strong>
    </div>
  );
}

function NavigationRail() {
  const items = [
    ['home', '主页'],
    ['scope', '传感器'],
    ['map', '地图'],
    ['terminal', '终端'],
    ['clipboard', '任务'],
    ['settings', '设置']
  ];
  return (
    <nav className="nav-rail" aria-label="控制台分区">
      {items.map(([name, label], index) => (
        <button className={index === 0 ? 'active' : ''} key={name} title={label}>
          <Icon name={name} />
        </button>
      ))}
    </nav>
  );
}

function ServicePanel({ status, rosbridge, telemetry }) {
  const modules = [
    { label: '底盘串口', ok: status.devices.chassisSerial, detail: status.devices.chassisPath ?? '串口缺失' },
    { label: '运动驱动', ok: status.services.chassis, detail: 'Mcnamu_driver_X3' },
    { label: '雷达扫描', ok: telemetry.lidar.connected || (status.devices.lidar && status.services.lidar), detail: '/scan' },
    { label: '摄像头视频', ok: status.ports.video6500, detail: '6500 MJPEG' },
    { label: 'IMU', ok: telemetry.imu.connected, detail: '/imu/data_raw' },
    { label: '电池电压', ok: telemetry.voltage.connected, detail: '/voltage' },
    { label: 'ROSBridge', ok: rosbridge.connected || status.ports.rosbridge9090, detail: '9090' },
    { label: '视频代理', ok: status.ports.video6500, detail: '6500' }
  ];
  const serviceRows = [
    ['底盘驱动', status.services.chassis],
    ['雷达驱动', status.services.lidar],
    ['相机节点', status.services.camera],
    ['ROSBridge', rosbridge.connected],
    ['视频流', status.ports.video6500],
    ['TCP 控制 6000', status.ports.control6000]
  ];

  return (
    <aside className="services-panel panel">
      <h2>服务</h2>
      <div className="service-switches">
        {serviceRows.map(([label, ok]) => (
          <div className="service-row" key={label}>
            <span className={`dot ${ok ? 'ok' : 'idle'}`} />
            <span>{label}</span>
            <button title={`启动${label}`}><Icon name="play" /></button>
            <button title={`停止${label}`}><Icon name="square" /></button>
          </div>
        ))}
      </div>
      <div className="panel-rule" />
      <h2>模块状态</h2>
      <div className="module-list">
        {modules.map((item) => (
          <div className="module-row" key={item.label}>
            <Icon name="chip" />
            <span>{item.label}</span>
            <small>{item.detail}</small>
            <strong className={item.ok ? 'ok-text' : 'warn-text'}>{item.ok ? '正常' : '缺失'}</strong>
          </div>
        ))}
      </div>
    </aside>
  );
}

function CameraPanel({ host, videoReady }) {
  const [imageOk, setImageOk] = useState(true);
  const [aiImageOk, setAiImageOk] = useState(true);
  const [aiMode, setAiMode] = useState(false);
  const [aiStats, setAiStats] = useState(null);
  useEffect(() => { setImageOk(true); setAiImageOk(true); }, [host, videoReady]);

  // AI stats polling
  useEffect(() => {
    if (!aiMode) { setAiStats(null); return; }
    const poll = () => {
      fetch('/api/ai-alarms').then(r => r.json()).then(d => {
        fetch('/api/ai-perf').then(r => r.json()).then(p => {
          setAiStats({ alarms: d, perf: p });
        }).catch(() => {});
      }).catch(() => {});
    };
    poll();
    const id = setInterval(poll, 3000);
    return () => clearInterval(id);
  }, [aiMode]);

  const showRaw = !aiMode && videoReady && imageOk;
  const showAi = aiMode && aiImageOk;

  return (
    <section className="panel media-panel">
      <PanelTitle title="摄像头" right={
        <div style={{display:'flex',gap:4,alignItems:'center'}}>
          <button onClick={() => setAiMode(false)}
            style={{background:aiMode?'#21262d':'#30363d',border:'1px solid #30363d',color:aiMode?'#8b949e':'#58a6ff',borderRadius:4,padding:'2px 8px',fontSize:11,cursor:'pointer'}}>
            原始画面
          </button>
          <button onClick={() => setAiMode(true)}
            style={{background:aiMode?'#30363d':'#21262d',border:'1px solid #30363d',color:aiMode?'#58a6ff':'#8b949e',borderRadius:4,padding:'2px 8px',fontSize:11,cursor:'pointer'}}>
            AI检测
          </button>
        </div>
      } />
      <div className="camera-frame" style={{position:'relative'}}>
        {aiMode ? (
          showAi ? (
            <>
              <img src="/api/ai-video" alt="AI检测视频流"
                onError={() => setAiImageOk(false)} />
              {aiStats && (
                <div style={{position:'absolute',top:8,right:8,background:'rgba(0,0,0,0.7)',borderRadius:6,padding:'6px 10px',fontSize:11,color:'#c9d1d9',lineHeight:1.6}}>
                  <div>FPS: <span style={{color:'#58a6ff'}}>{aiStats.perf?.fps ?? '--'}</span></div>
                  <div>人员: <span style={{color:'#3fb950'}}>{aiStats.alarms?.total_by_type?.person_detected ?? 0}</span></div>
                  <div>异常: <span style={{color:'#f85149'}}>{aiStats.alarms?.total_by_type?.abnormal_behavior ?? 0}</span></div>
                  <div>裂缝: <span style={{color:'#f0883e'}}>{aiStats.alarms?.total_by_type?.cracked_tile ?? 0}</span></div>
                </div>
              )}
            </>
          ) : (
            <div className="camera-placeholder">
              <Icon name="camera" />
              <strong>AI检测视频流未连接</strong>
              <span>请确保 Jetson 上 ai_web_bridge 正在运行 (端口 6501)</span>
            </div>
          )
        ) : (
          showRaw ? (
            <img src={`/api/video?host=${encodeURIComponent(host)}`} alt="摄像头视频流"
              onError={() => setImageOk(false)} />
          ) : (
            <div className="camera-placeholder">
              <Icon name="camera" />
              <strong>视频流未连接</strong>
              <span>启动服务后代理 http://{host}:6500/video_feed</span>
            </div>
          )
        )}
      </div>
      <div className="media-footer">
        <span>{aiMode ? (showAi ? 'AI检测' : '等待AI检测流') : (showRaw ? 'MJPEG 代理已启用' : '等待视频流')}</span>
        <span>{host}{aiMode ? ':6501 (AI检测)' : ':6500 (原始)'}</span>
      </div>
    </section>
  );
}

function LidarPanel({ lidar }) {
  const canvasRef = useRef(null);
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.floor(width * dpr);
    canvas.height = Math.floor(height * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    drawLidar(ctx, width, height, lidar);
  }, [lidar]);

  return (
    <section className="panel lidar-panel">
      <PanelTitle title="雷达" right={<div className="mode-pill">2D</div>} />
      <div className="lidar-canvas-wrap">
        <canvas ref={canvasRef} />
      </div>
      <div className="media-footer">
        <span>{lidar.connected ? `${lidar.points.length} 个扫描点` : '无 /scan 数据'}</span>
        <span>{fmt(lidar.rangeMax, ' m')}</span>
      </div>
    </section>
  );
}

function drawLidar(ctx, width, height, lidar) {
  ctx.clearRect(0, 0, width, height);
  const cx = width / 2;
  const cy = height / 2 + 8;
  const radius = Math.min(width, height) * 0.42;
  const maxRange = Math.max(2, lidar.rangeMax || 12);
  ctx.fillStyle = '#091014';
  ctx.fillRect(0, 0, width, height);

  ctx.strokeStyle = '#20313a';
  ctx.lineWidth = 1;
  for (let ring = 1; ring <= 4; ring += 1) {
    ctx.beginPath();
    ctx.arc(cx, cy, (radius / 4) * ring, 0, Math.PI * 2);
    ctx.stroke();
  }
  for (let line = 0; line < 8; line += 1) {
    const angle = (Math.PI * 2 / 8) * line;
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(cx + Math.cos(angle) * radius, cy + Math.sin(angle) * radius);
    ctx.stroke();
  }

  ctx.strokeStyle = '#0d7b68';
  ctx.beginPath();
  ctx.arc(cx, cy, radius * 0.34, 0, Math.PI * 2);
  ctx.stroke();

  const points = lidar.connected ? lidar.points : standbyScan();
  for (const point of points) {
    const normalized = Math.min(point.range / maxRange, 1);
    const x = cx + Math.cos(point.angle - Math.PI / 2) * radius * normalized;
    const y = cy + Math.sin(point.angle - Math.PI / 2) * radius * normalized;
    const hue = 130 - Math.min(110, normalized * 110);
    ctx.fillStyle = lidar.connected ? `hsl(${hue} 92% 48%)` : '#243842';
    ctx.fillRect(x, y, lidar.connected ? 2 : 1.2, lidar.connected ? 2 : 1.2);
  }

  ctx.fillStyle = '#dbe8f1';
  ctx.beginPath();
  ctx.roundRect(cx - 12, cy - 18, 24, 36, 8);
  ctx.fill();
  ctx.fillStyle = '#222a31';
  ctx.fillRect(cx - 8, cy - 10, 16, 20);
  ctx.strokeStyle = '#f0f6fa';
  ctx.strokeRect(cx - 12, cy - 18, 24, 36);

  ctx.fillStyle = '#8294a0';
  ctx.font = '12px ui-monospace, SFMono-Regular, Consolas, monospace';
  ctx.fillText('10m', 12, 28);
  ctx.fillText('0m', 16, cy - 6);
  if (!lidar.connected) {
    ctx.fillStyle = '#61717b';
    ctx.fillText('standby', width - 72, height - 16);
  }
}

function standbyScan() {
  const points = [];
  for (let i = 0; i < 160; i += 1) {
    const angle = i * 0.17;
    const wave = 7.2 + Math.sin(i * 0.29) * 1.8 + Math.cos(i * 0.07) * 0.7;
    if (i % 4 !== 0) points.push({ angle, range: wave });
  }
  return points;
}

function Joystick({ disabled, vector, keyboardActive, onVector, onStop }) {
  const padRef = useRef(null);
  const activeRef = useRef(false);

  const updateFromEvent = useCallback((event) => {
    if (!activeRef.current || disabled) return;
    const rect = padRef.current.getBoundingClientRect();
    const cx = rect.left + rect.width / 2;
    const cy = rect.top + rect.height / 2;
    const max = rect.width * 0.42;
    const dx = Math.max(-max, Math.min(max, event.clientX - cx));
    const dy = Math.max(-max, Math.min(max, event.clientY - cy));
    onVector({
      forward: roundClient(-dy / max),
      turn: roundClient(dx / max),
      strafe: 0
    });
  }, [disabled, onVector]);

  return (
    <section className={`panel joystick-panel ${disabled ? 'disabled' : ''}`}>
      <PanelTitle
        title="摇杆"
        right={(
          <span className="keyboard-status" title="W/S 前后，A/D 转向，Q/E 横移，空格急停">
            <Icon name="keyboard" />
            {disabled ? '锁定' : keyboardActive ? '键盘控制中' : '就绪'}
          </span>
        )}
      />
      <div
        ref={padRef}
        className="joystick-pad"
        onPointerDown={(event) => {
          if (disabled) return;
          activeRef.current = true;
          event.currentTarget.setPointerCapture(event.pointerId);
          updateFromEvent(event);
        }}
        onPointerMove={updateFromEvent}
        onPointerUp={(event) => {
          activeRef.current = false;
          event.currentTarget.releasePointerCapture(event.pointerId);
          onStop();
        }}
        onPointerCancel={onStop}
      >
        <span className="arrow up">^</span>
        <span className="arrow down">v</span>
        <span className="arrow left">&lt;</span>
        <span className="arrow right">&gt;</span>
        <div
          className="stick"
          style={{
            transform: `translate(${vector.turn * 45}px, ${-vector.forward * 45}px)`
          }}
        />
      </div>
      <div className="joystick-readout">
        <span>前后 <strong>{vector.forward.toFixed(2)}</strong></span>
        <span>转向 <strong>{vector.turn.toFixed(2)}</strong></span>
        <span>横移 <strong>{(vector.strafe ?? 0).toFixed(2)}</strong></span>
      </div>
    </section>
  );
}

function SpeedPanel({
  linearLimit,
  angularLimit,
  maxLinear,
  maxAngular,
  setLinearLimit,
  setAngularLimit,
  onEmergency,
  disabled
}) {
  return (
    <section className="panel speed-panel">
      <PanelTitle title="速度上限" right={<span className="small-help">{disabled ? '运动锁定' : '低速模式'}</span>} />
      <label className="slider-row">
        <span>线速度</span>
        <input type="range" min="0.05" max={maxLinear} step="0.01" value={linearLimit} onChange={(event) => setLinearLimit(Number(event.target.value))} />
        <strong>{linearLimit.toFixed(2)} m/s</strong>
      </label>
      <label className="slider-row">
        <span>角速度</span>
        <input type="range" min="0.10" max={maxAngular} step="0.05" value={angularLimit} onChange={(event) => setAngularLimit(Number(event.target.value))} />
        <strong>{angularLimit.toFixed(2)} rad/s</strong>
      </label>
      <button className="emergency-button" onClick={onEmergency}>
        <Icon name="stop" />
        急停
      </button>
    </section>
  );
}

function ServiceActions({ busy, onStart, onStop, onRefresh }) {
  return (
    <section className="panel action-panel">
      <PanelTitle title="服务控制" />
      <div className="action-grid">
        <button className="primary-action" disabled={Boolean(busy)} onClick={onStart}>
          <Icon name="play" />
          {busy === 'start' ? '启动中' : '启动全部'}
        </button>
        <button className="danger-action" disabled={Boolean(busy)} onClick={onStop}>
          <Icon name="square" />
          {busy === 'stop' ? '停止中' : '停止全部'}
        </button>
        <button onClick={onRefresh}>
          <Icon name="refresh" />
          刷新
        </button>
        <button disabled>
          <Icon name="power" />
          关闭小车
        </button>
      </div>
    </section>
  );
}

function SensorInspector({ telemetry, status, blockers }) {
  const mainBatteryPercent = batteryPercent(telemetry.voltage);
  const accessoryRows = accessoryPowerRows(telemetry, status);
  return (
    <aside className="inspector panel">
      <h2>传感器面板</h2>
      <SensorCard title="IMU 姿态" connected={telemetry.imu.connected}>
        <DataGrid rows={[
          ['航向角 deg', telemetry.imu.orientation.yaw],
          ['横滚角 deg', telemetry.imu.orientation.roll],
          ['俯仰角 deg', telemetry.imu.orientation.pitch],
          ['加速度 X', telemetry.imu.acceleration.x],
          ['加速度 Y', telemetry.imu.acceleration.y],
          ['加速度 Z', telemetry.imu.acceleration.z],
          ['角速度 X', telemetry.imu.gyro.x],
          ['角速度 Y', telemetry.imu.gyro.y],
          ['角速度 Z', telemetry.imu.gyro.z],
          ['磁力计 X', telemetry.imu.magnetometer.x],
          ['磁力计 Y', telemetry.imu.magnetometer.y],
          ['磁力计 Z', telemetry.imu.magnetometer.z]
        ]} />
      </SensorCard>
      <SensorCard
        title="电源与电量"
        connected={telemetry.voltage.connected}
        reason={telemetry.voltage.connected ? '主车电量按 /voltage 电压保守估算；附属设备当前未发现独立电量数据源。' : '主车 /voltage 未连接'}
      >
        <DataGrid rows={[
          ['主车电池电压', fmt(telemetry.voltage.battery, ' V')],
          ['主车电量估算', formatPercent(mainBatteryPercent)],
          ['电流', fmt(telemetry.voltage.current, ' A')],
          ['功率', fmt(telemetry.voltage.power, ' W')]
        ]} />
        <BatteryBar percent={mainBatteryPercent} label={formatPercent(mainBatteryPercent)} />
        <div className="sensor-subtitle">附属设备电量</div>
        <DataGrid rows={accessoryRows} />
      </SensorCard>
      <SensorCard title="编码器" connected={telemetry.encoders.connected}>
        <DataGrid rows={[
          ['左轮计数', telemetry.encoders.leftTicks],
          ['右轮计数', telemetry.encoders.rightTicks],
          ['计数增量', telemetry.encoders.deltaTicks],
          ['左轮 rad/s', telemetry.encoders.leftRadPerSec],
          ['右轮 rad/s', telemetry.encoders.rightRadPerSec]
        ]} />
      </SensorCard>
      <SensorCard title="速度" connected={telemetry.velocity.connected}>
        <DataGrid rows={[
          ['线速度 m/s', telemetry.velocity.linear],
          ['角速度 rad/s', telemetry.velocity.angular]
        ]} />
      </SensorCard>
      <SensorCard title="环境传感器" connected={telemetry.environment.connected} reason={telemetry.environment.reason}>
        <DataGrid rows={[
          ['温度', telemetry.environment.temperature],
          ['湿度', telemetry.environment.humidity],
          ['气压', telemetry.environment.pressure],
          ['空气质量', telemetry.environment.airQuality],
          ['环境光', telemetry.environment.ambientLight],
          ['声音强度', telemetry.environment.soundLevel]
        ]} />
      </SensorCard>
      {!status.canDrive && (
        <div className="drive-lock">
          <strong>运动锁定</strong>
          {blockers.map((blocker) => <span key={blocker}>{translateBlocker(blocker)}</span>)}
        </div>
      )}
    </aside>
  );
}

function SensorCard({ title, connected, reason, children }) {
  return (
    <section className="sensor-card">
      <header>
        <strong>{title}</strong>
        <span className={connected ? 'ok-text' : 'bad-text'}>{connected ? '正常' : '未连接'}</span>
      </header>
      {reason && <p>{reason}</p>}
      {children}
    </section>
  );
}

function DataGrid({ rows }) {
  return (
    <div className="data-grid">
      {rows.map(([label, value]) => (
        <div key={label}>
          <span>{label}</span>
          <strong>{value === null || value === undefined || value === 'Not connected' || value === '未连接' ? '未连接' : value}</strong>
        </div>
      ))}
    </div>
  );
}

function BatteryBar({ percent, label }) {
  const width = percent == null ? 0 : Math.max(0, Math.min(100, percent));
  return (
    <div className="battery-bar">
      <span style={{ width: `${width}%` }} />
      {label && <strong>{label}</strong>}
    </div>
  );
}

function LogConsole({ logs }) {
  const listRef = useRef(null);
  useEffect(() => {
    const element = listRef.current;
    if (element) element.scrollTop = element.scrollHeight;
  }, [logs]);
  return (
    <section className="panel log-panel">
      <PanelTitle
        title="日志控制台"
        right={(
          <div className="log-tools">
            <button>清空</button>
            <button>暂停</button>
            <label><input type="checkbox" checked readOnly /> 自动滚动</label>
            <button><Icon name="trash" /></button>
          </div>
        )}
      />
      <div ref={listRef} className="log-list">
        {logs.length === 0 ? (
          <pre><span className="log-muted">等待 API 事件...</span></pre>
        ) : logs.slice(-80).map((log) => (
          <pre key={log.id}>
            <span>{new Date(log.ts).toLocaleTimeString()}</span>
            <span className={`log-${log.level}`}>[{log.level.toUpperCase()}]</span>
            <span>[{log.scope}]</span>
            <span>{log.message}</span>
          </pre>
        ))}
      </div>
    </section>
  );
}

function ConfigDialog({ config, onClose, onSaved }) {
  const [form, setForm] = useState({
    host: config.car.host,
    sshUser: config.car.sshUser,
    sshPassword: '',
    sshHostKey: config.car.sshHostKey,
    plinkPath: config.car.plinkPath
  });
  const [saving, setSaving] = useState(false);

  async function save(event) {
    event.preventDefault();
    setSaving(true);
    try {
      const response = await fetch('/api/config', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          car: {
            host: form.host,
            sshUser: form.sshUser,
            sshPassword: form.sshPassword,
            sshHostKey: form.sshHostKey,
            plinkPath: form.plinkPath
          }
        })
      });
      const body = await response.json();
      if (body.config) onSaved(body.config);
      onClose();
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="dialog-backdrop" role="presentation">
      <form className="dialog panel" onSubmit={save}>
        <PanelTitle title="连接设置" right={<button type="button" className="icon-button" onClick={onClose}><Icon name="square" /></button>} />
        <label>
          <span>小车 IP</span>
          <input value={form.host} onChange={(event) => setForm({ ...form, host: event.target.value })} />
        </label>
        <label>
          <span>SSH 用户</span>
          <input value={form.sshUser} onChange={(event) => setForm({ ...form, sshUser: event.target.value })} />
        </label>
        <label>
          <span>SSH 密码</span>
          <input type="password" placeholder={config.car.sshPasswordSet ? '已保存密码' : ''} value={form.sshPassword} onChange={(event) => setForm({ ...form, sshPassword: event.target.value })} />
        </label>
        <label>
          <span>SSH 主机密钥</span>
          <input value={form.sshHostKey} onChange={(event) => setForm({ ...form, sshHostKey: event.target.value })} />
        </label>
        <label>
          <span>Plink 路径</span>
          <input value={form.plinkPath} onChange={(event) => setForm({ ...form, plinkPath: event.target.value })} />
        </label>
        <div className="dialog-actions">
          <button type="button" onClick={onClose}>取消</button>
          <button className="primary-action" disabled={saving}>{saving ? '保存中' : '保存'}</button>
        </div>
      </form>
    </div>
  );
}

function PanelTitle({ title, right }) {
  return (
    <header className="panel-title">
      <h2>{title}</h2>
      {right && <div>{right}</div>}
    </header>
  );
}

function ToolbarIcons({ names }) {
  const titles = {
    camera: '截图',
    fullscreen: '全屏',
    more: '更多'
  };
  return (
    <div className="toolbar-icons">
      {names.map((name) => <button key={name} title={titles[name] ?? name}><Icon name={name} /></button>)}
    </div>
  );
}

function fmt(value, suffix = '') {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '未连接';
  return `${Number(value).toFixed(Math.abs(value) >= 10 ? 1 : 2)}${suffix}`;
}

function formatBatterySummary(voltage) {
  const battery = fmt(voltage?.battery, ' V');
  if (battery === '未连接') return battery;
  const percent = batteryPercent(voltage);
  return percent === null ? battery : `${battery} / ${percent}%`;
}

function batteryPercent(voltage) {
  const estimated = estimateBatteryPercent(voltage?.battery ?? voltage?.voltage);
  if (estimated !== null) return estimated;
  const direct = Number(voltage?.percent);
  return Number.isFinite(direct) ? Math.max(0, Math.min(100, Math.round(direct))) : null;
}

function estimateBatteryPercent(value) {
  const voltage = Number(value);
  if (!Number.isFinite(voltage)) return null;
  const emptyVoltage = 9.6;
  const fullVoltage = 12.6;
  return Math.max(0, Math.min(100, Math.round((voltage - emptyVoltage) / (fullVoltage - emptyVoltage) * 100)));
}

function formatPercent(value) {
  return value === null || value === undefined ? '未连接' : `${value}%`;
}

function accessoryPowerRows(telemetry, status) {
  const explicitDevices = telemetry.accessoryPower?.devices;
  if (Array.isArray(explicitDevices) && explicitDevices.length > 0) {
    return explicitDevices.map((device) => [
      device.label ?? device.name ?? device.id ?? '附属设备',
      formatAccessoryPower(device)
    ]);
  }

  return [
    ['Jetson/计算单元', status.ssh.connected ? '共用主车电源，无独立读数' : '离线'],
    ['底盘控制板', status.devices.chassisSerial ? '共用主车电源，无独立读数' : '未连接'],
    ['雷达', status.devices.lidar ? '共用主车电源，无独立读数' : '未连接'],
    ['摄像头', (status.devices.video0 || status.devices.cameraDepth || status.devices.cameraUvc) ? '共用主车电源，无独立读数' : '未连接']
  ];
}

function formatAccessoryPower(device) {
  const parts = [];
  const percent = batteryPercent(device);
  if (percent !== null) parts.push(`${percent}%`);
  if (device.voltage !== null && device.voltage !== undefined) parts.push(fmt(device.voltage, ' V'));
  if (device.current !== null && device.current !== undefined) parts.push(fmt(device.current, ' A'));
  if (parts.length > 0) return parts.join(' / ');
  return device.reason ?? device.status ?? '未连接';
}

function translateBlocker(blocker) {
  const translations = {
    'Chassis serial device is missing': '底盘串口设备缺失',
    'Chassis driver is not running': '底盘驱动未运行',
    'RPLidar device is missing': '雷达设备缺失',
    'Lidar driver is not running': '雷达驱动未运行',
    'Camera device is missing': '摄像头设备缺失',
    'Camera stream is not running': '摄像头视频流未运行',
    'ROSBridge is not connected': 'ROSBridge 未连接',
    'Status has not been refreshed': '状态尚未刷新',
    'Waiting for status check': '等待状态检查'
  };
  return translations[blocker] ?? blocker;
}

function roundClient(value) {
  return Math.round(value * 100) / 100;
}

function Icon({ name }) {
  const paths = {
    car: <><path d="M4 13l2-5h12l2 5" /><path d="M5 13h14v5H5z" /><circle cx="8" cy="18" r="1.6" /><circle cx="16" cy="18" r="1.6" /></>,
    home: <><path d="M4 11l8-7 8 7" /><path d="M6 10v10h12V10" /><path d="M10 20v-6h4v6" /></>,
    scope: <><path d="M5 18h14" /><path d="M7 15l3-7 4 5 3-9" /><circle cx="7" cy="15" r="1" /><circle cx="17" cy="4" r="1" /></>,
    map: <><path d="M5 5l5-2 4 2 5-2v16l-5 2-4-2-5 2z" /><path d="M10 3v16" /><path d="M14 5v16" /></>,
    terminal: <><path d="M5 7l5 5-5 5" /><path d="M12 17h7" /></>,
    clipboard: <><path d="M8 5h8v3H8z" /><path d="M6 7h12v13H6z" /></>,
    settings: <><circle cx="12" cy="12" r="3" /><path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M18.4 5.6l-2.1 2.1M7.7 16.3l-2.1 2.1" /></>,
    play: <path d="M8 5l10 7-10 7z" />,
    square: <path d="M7 7h10v10H7z" />,
    stop: <path d="M7 7h10v10H7z" />,
    refresh: <><path d="M19 8a7 7 0 10-2 7" /><path d="M19 4v4h-4" /></>,
    power: <><path d="M12 3v9" /><path d="M6.5 7.5a7 7 0 1011 0" /></>,
    camera: <><path d="M5 8h3l1.5-2h5L16 8h3v10H5z" /><circle cx="12" cy="13" r="3" /></>,
    fullscreen: <><path d="M5 9V5h4M15 5h4v4M19 15v4h-4M9 19H5v-4" /></>,
    more: <><circle cx="12" cy="6" r="1" /><circle cx="12" cy="12" r="1" /><circle cx="12" cy="18" r="1" /></>,
    trash: <><path d="M6 7h12" /><path d="M9 7V5h6v2" /><path d="M8 7l1 13h6l1-13" /></>,
    chip: <><rect x="7" y="7" width="10" height="10" rx="2" /><path d="M4 10h3M4 14h3M17 10h3M17 14h3M10 4v3M14 4v3M10 17v3M14 17v3" /></>
    ,
    keyboard: <><path d="M4 7h16v10H4z" /><path d="M7 10h.1M10 10h.1M13 10h.1M16 10h.1M7 13h6M16 13h1" /></>
  };
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      {paths[name] ?? paths.chip}
    </svg>
  );
}
