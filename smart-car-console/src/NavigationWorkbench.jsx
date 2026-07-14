import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  WORKBENCH_TABS,
  configuredMapId,
  emptyRoute,
  navigationBlockers,
  numericRoutePoint,
  previewPoint,
  setRoutePoint
} from './navigationWorkbench.js';

export default function NavigationWorkbench({ config, runtime, telemetry, onRefresh, onOpenRemote }) {
  const [tab, setTab] = useState('mapping');
  const [maps, setMaps] = useState([]);
  const [selectedMap, setSelectedMap] = useState(configuredMapId(config));
  const [preview, setPreview] = useState(null);
  const [pose, setPose] = useState({ x: 0, y: 0, yaw: 0 });
  const [route, setRoute] = useState(emptyRoute());
  const [routePoint, setRoutePointIndex] = useState(0);
  const [mapName, setMapName] = useState('campus_map');
  const [busy, setBusy] = useState(null);
  const [notice, setNotice] = useState(null);
  const [operation, setOperation] = useState(null);
  const motionAcknowledged = Boolean(config?.safety?.motionWarningAcknowledged);
  const navigation = runtime?.navigation ?? {};
  const activeMap = configuredMapId(config);

  const request = useCallback(async (path, options = {}) => {
    setBusy(path);
    setNotice(null);
    try {
      const response = await fetch(path, {
        ...options,
        headers: options.body ? { 'content-type': 'application/json', ...(options.headers ?? {}) } : options.headers
      });
      const payload = await response.json();
      if (!response.ok || payload.ok === false) {
        const blockers = payload.blockers?.length ? `（${payload.blockers.join('；')}）` : '';
        throw new Error(`${payload.message || payload.error || '操作失败'}${blockers}`);
      }
      setNotice({ tone: 'success', text: payload.message || '操作成功' });
      if (payload.operation) setOperation(payload.operation);
      return payload;
    } catch (error) {
      setNotice({ tone: 'error', text: error.message });
      throw error;
    } finally {
      setBusy(null);
    }
  }, []);

  const refreshMaps = useCallback(async () => {
    try {
      const response = await fetch('/api/maps', { cache: 'no-store' });
      const payload = await response.json();
      if (response.ok && payload.maps) {
        setMaps(payload.maps);
        setSelectedMap((current) => current || payload.maps.find((map) => map.active)?.id || payload.maps[0]?.id || null);
      }
    } catch {
      // The visible status and manual refresh button communicate an offline car.
    }
  }, []);

  useEffect(() => { void refreshMaps(); }, [refreshMaps]);

  useEffect(() => {
    if (!selectedMap) { setPreview(null); return; }
    fetch(`/api/maps/${encodeURIComponent(selectedMap)}/preview`, { cache: 'no-store' })
      .then(async (response) => {
        const payload = await response.json();
        if (!response.ok || !payload.preview) throw new Error(payload.message || 'Map preview unavailable');
        setPreview(payload.preview);
      })
      .catch(() => setPreview(null));
    fetch(`/api/routes/${encodeURIComponent(selectedMap)}`, { cache: 'no-store' })
      .then(async (response) => {
        const payload = await response.json();
        if (!response.ok || !payload.route) throw new Error(payload.message || 'Route unavailable');
        setRoute(payload.route);
      })
      .catch(() => setRoute(emptyRoute()));
  }, [selectedMap]);

  useEffect(() => {
    if (!operation || operation.status !== 'RUNNING') return undefined;
    const timer = window.setInterval(async () => {
      try {
        const response = await fetch('/api/navigation/operations/current', { cache: 'no-store' });
        const payload = await response.json();
        if (payload.operation) {
          setOperation(payload.operation);
          if (payload.operation.status !== 'RUNNING') {
            await refreshMaps();
            await onRefresh?.();
          }
        }
      } catch { /* keep the last operation state */ }
    }, 800);
    return () => window.clearInterval(timer);
  }, [onRefresh, operation, refreshMaps]);

  const blockers = useMemo(() => navigationBlockers({ config, navigation, telemetry, motionAcknowledged }), [config, motionAcknowledged, navigation, telemetry]);

  async function switchMode(mode) {
    await request('/api/navigation/mode', { method: 'POST', body: JSON.stringify({ mode }) });
  }

  async function acknowledgeMotion() {
    await request('/api/safety/motion-warning/ack', { method: 'POST' });
    await onRefresh?.();
  }

  async function placePose(nextPose) {
    setPose(nextPose);
  }

  async function saveRoute() {
    if (!selectedMap) return;
    const configured = {
      ...route,
      configured: true,
      default_dwell_sec: Number(route.default_dwell_sec),
      max_retries: Number(route.max_retries),
      home: numericRoutePoint(route.home),
      waypoints: route.waypoints.map(numericRoutePoint)
    };
    const payload = await request(`/api/routes/${encodeURIComponent(selectedMap)}`, { method: 'PUT', body: JSON.stringify(configured) });
    setRoute(payload.route);
  }

  return (
    <section className="panel navigation-workbench">
      <header className="navigation-workbench-header">
        <div>
          <h2>建图与导航工作台</h2>
          <p>候选地图需先校验并激活；切换导航后仍须设置初始位姿。</p>
        </div>
        <div className="workbench-summary">
          <span className="mode-pill">{config?.navigation?.mode ?? 'safe_base'}</span>
          <span className={`mode-pill ${navigation?.safetyState === 'READY' ? '' : 'warn'}`}>{navigation?.safetyState ?? 'UNKNOWN'}</span>
          <span className="mode-pill">目标 {navigation?.goal?.state ?? navigation?.action?.status ?? 'IDLE'}</span>
        </div>
      </header>
      <div className="navigation-tabs" role="tablist">
        {WORKBENCH_TABS.map(([key, label], index) => (
          <button key={key} className={tab === key ? 'active' : ''} onClick={() => setTab(key)}>
            <b>{index + 1}</b>{label}
          </button>
        ))}
      </div>

      {notice && <div className={`workbench-notice ${notice.tone}`}>{notice.text}</div>}
      {operation && <OperationStrip operation={operation} />}

      {tab === 'mapping' && (
        <div className="workbench-content mapping-step">
          <WorkbenchSidebar title="建图门禁" rows={[
            ['运行模式', config?.navigation?.mode],
            ['Cartographer /map', telemetry?.map?.connected ? '正常' : '未就绪'],
            ['栅格尺寸', telemetry?.map?.connected ? `${telemetry.map.width} × ${telemetry.map.height}` : '-'],
            ['保存规则', 'PGM + YAML + PBStream']
          ]} />
          <div className="workbench-main">
            <LiveMapSummary telemetry={telemetry} />
            <div className="workbench-actions">
              <button disabled={Boolean(busy) || config?.navigation?.mode === 'mapping'} onClick={() => switchMode('mapping')}>切换到 mapping</button>
              <button onClick={onOpenRemote}>打开低速遥控</button>
              <label>地图名称<input value={mapName} onChange={(event) => setMapName(event.target.value)} /></label>
              <button className="primary-action" disabled={Boolean(busy) || config?.navigation?.mode !== 'mapping' || !telemetry?.map?.connected} onClick={() => request('/api/maps/save', { method: 'POST', body: JSON.stringify({ name: mapName }) })}>保存候选地图</button>
            </div>
            <Blockers items={[
              ...(config?.navigation?.mode === 'mapping' ? [] : ['当前不是 mapping 模式']),
              ...(telemetry?.map?.connected ? [] : ['Cartographer /map 尚未就绪'])
            ]} />
          </div>
        </div>
      )}

      {tab === 'maps' && (
        <div className="workbench-content maps-step">
          <MapList maps={maps} selected={selectedMap} onSelect={setSelectedMap} />
          <div className="workbench-main">
            <InteractiveMap preview={preview} pose={pose} telemetry={telemetry} readOnly />
            <div className="workbench-actions wrap">
              <button onClick={refreshMaps}>刷新地图</button>
              <button disabled={!selectedMap} onClick={() => request(`/api/maps/${encodeURIComponent(selectedMap)}/verify`, { method: 'POST' })}>校验</button>
              <button className="primary-action" disabled={!selectedMap || selectedMap === activeMap || ['navigation', 'demo'].includes(config?.navigation?.mode)} onClick={async () => { await request(`/api/maps/${encodeURIComponent(selectedMap)}/activate`, { method: 'POST' }); await onRefresh?.(); await refreshMaps(); }}>激活</button>
              <button disabled={!selectedMap || selectedMap === activeMap} onClick={async () => { await request(`/api/maps/${encodeURIComponent(selectedMap)}/archive`, { method: 'POST' }); await refreshMaps(); }}>归档</button>
              <button disabled={!selectedMap} onClick={async () => { await request(`/api/maps/${encodeURIComponent(selectedMap)}/restore`, { method: 'POST' }); await refreshMaps(); }}>恢复</button>
              {['pgm', 'yaml', 'pbstream'].map((ext) => <a key={ext} className="button-link" href={selectedMap ? `/api/maps/${encodeURIComponent(selectedMap)}/files/${ext}` : undefined}>{ext.toUpperCase()}</a>)}
            </div>
            <div className="import-row">
              <input value={mapName} onChange={(event) => setMapName(event.target.value)} />
              <button onClick={async () => { await request('/api/maps/import-active', { method: 'POST', body: JSON.stringify({ name: mapName }) }); await refreshMaps(); }}>显式导入旧配置地图</button>
            </div>
            <Blockers items={['navigation', 'demo'].includes(config?.navigation?.mode) ? ['请先切换到 safe_base 或 mapping，再激活地图'] : []} />
          </div>
        </div>
      )}

      {tab === 'localization' && (
        <PoseStep title="设置初始位姿" preview={preview} telemetry={telemetry} pose={pose} onPose={placePose} side={(
          <>
            <button disabled={config?.navigation?.mode === 'navigation'} onClick={() => switchMode('navigation')}>切换到 navigation</button>
            <button className="primary-action" disabled={config?.navigation?.mode !== 'navigation' || !activeMap} onClick={() => request('/api/localization/initial-pose', { method: 'POST', body: JSON.stringify(pose) })}>发布 /initialpose</button>
            <p>定位状态：{telemetry?.pose?.connected && !telemetry?.pose?.stale ? 'AMCL / TF 新鲜，定位就绪' : '等待新鲜 AMCL / TF'}</p>
            <Blockers items={[...(!activeMap ? ['没有已激活地图'] : []), ...(config?.navigation?.mode !== 'navigation' ? ['当前不是 navigation 模式'] : []), ...(!telemetry?.pose?.connected || telemetry?.pose?.stale ? ['AMCL / TF 尚未新鲜'] : [])]} />
          </>
        )} />
      )}

      {tab === 'goal' && (
        <PoseStep title="单点导航目标" preview={preview} telemetry={telemetry} pose={pose} onPose={placePose} side={(
          <>
            <button className="primary-action" disabled={Boolean(busy) || blockers.length > 0} onClick={() => request('/api/navigation/goals', { method: 'POST', body: JSON.stringify(pose) })}>发送单点目标</button>
            <button className="danger" onClick={() => request('/api/navigation/goals/current', { method: 'DELETE' })}>随时取消</button>
            <p>当前目标：{navigation?.goal?.goalId ?? navigation?.goal?.goal_id ?? '-'}</p>
            <p>动作终态：{navigation?.goal?.state ?? navigation?.action?.status ?? 'IDLE'}</p>
            <p>图层：全局/局部路径、代价地图均来自实时 ROS 遥测。</p>
            <Blockers items={blockers} />
          </>
        )} />
      )}

      {tab === 'route' && (
        <div className="workbench-content route-step">
          <div className="workbench-main">
            <InteractiveMap preview={preview} telemetry={telemetry} pose={routePointValue(route, routePoint)} onPose={(next) => setRoute((current) => setRoutePoint(current, routePoint, next))} />
            <div className="route-point-selector">
              {['Home', '航点 1', '航点 2', '航点 3'].map((label, index) => <button key={label} className={routePoint === index ? 'active' : ''} onClick={() => setRoutePointIndex(index)}>{label}</button>)}
            </div>
          </div>
          <div className="route-editor">
            {[route.home, ...route.waypoints].map((point, index) => (
              <RoutePointEditor key={index} point={point} label={index === 0 ? 'Home' : `航点 ${index}`} onChange={(next) => setRoute((current) => setRoutePoint(current, index, next))} />
            ))}
            <div className="route-policy-grid">
              <label>默认停留<input type="number" min="0" step="0.1" value={route.default_dwell_sec} onChange={(event) => setRoute({ ...route, default_dwell_sec: event.target.value })} /></label>
              <label>重试<select value={route.max_retries} onChange={(event) => setRoute({ ...route, max_retries: event.target.value })}>{[0, 1, 2, 3].map((value) => <option key={value}>{value}</option>)}</select></label>
              <label>失败策略<select value={route.failure_policy} onChange={(event) => setRoute({ ...route, failure_policy: event.target.value })}><option value="skip">skip</option><option value="abort">abort</option></select></label>
              <label className="check-label"><input type="checkbox" checked={route.loop} onChange={(event) => setRoute({ ...route, loop: event.target.checked })} />循环</label>
            </div>
            <div className="workbench-actions wrap">
              <button onClick={saveRoute} disabled={!selectedMap}>保存路线</button>
              <button className="primary-action" disabled={navigationBlockers({ config, navigation, telemetry, motionAcknowledged, route }).length > 0} onClick={() => request('/api/patrol/start', { method: 'POST' })}>开始巡航</button>
              <button onClick={() => request('/api/patrol/cancel', { method: 'POST' })}>取消</button>
              <button disabled={!motionAcknowledged} onClick={() => request('/api/patrol/return-home', { method: 'POST' })}>返航</button>
              <button disabled={!motionAcknowledged} onClick={() => request('/api/safety/simulate-low-battery', { method: 'POST' })}>模拟低电</button>
            </div>
            <Blockers items={navigationBlockers({ config, navigation, telemetry, motionAcknowledged, route })} />
          </div>
        </div>
      )}

      {!motionAcknowledged && <MotionWarning onAcknowledge={acknowledgeMotion} busy={Boolean(busy)} />}
    </section>
  );
}

function PoseStep({ title, preview, telemetry, pose, onPose, side }) {
  return <div className="workbench-content pose-step"><div className="workbench-main"><InteractiveMap preview={preview} telemetry={telemetry} pose={pose} onPose={onPose} /><PoseEditor title={title} pose={pose} onChange={onPose} /></div><aside className="pose-actions">{side}</aside></div>;
}

function InteractiveMap({ preview, telemetry, pose, onPose, readOnly = false }) {
  const ref = useRef(null);
  const dragStart = useRef(null);
  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = '#081016'; ctx.fillRect(0, 0, canvas.width, canvas.height);
    if (preview?.pixels?.length) {
      const rows = preview.pixels.length; const columns = preview.pixels[0]?.length ?? 0;
      const sx = canvas.width / Math.max(columns, 1); const sy = canvas.height / Math.max(rows, 1);
      preview.pixels.forEach((row, y) => row.forEach((value, x) => {
        const shade = Math.max(18, Math.min(225, Number(value)));
        ctx.fillStyle = `rgb(${shade},${shade},${shade})`;
        ctx.fillRect(x * sx, y * sy, Math.ceil(sx), Math.ceil(sy));
      }));
    } else {
      ctx.fillStyle = '#8c9ba6'; ctx.font = '16px sans-serif'; ctx.fillText('选择完整地图后显示预览', 24, 40);
    }
    drawTelemetryPath(ctx, preview, canvas, telemetry?.globalPath, '#68a9ff');
    drawTelemetryPath(ctx, preview, canvas, telemetry?.localPath, '#f7d154');
    if (Number.isFinite(pose?.x) && Number.isFinite(pose?.y)) drawPose(ctx, preview, canvas, pose, '#12c9b7');
    const livePose = telemetry?.pose?.pose;
    if (Number.isFinite(livePose?.x)) drawPose(ctx, preview, canvas, livePose, '#f05252');
  }, [pose, preview, telemetry]);
  function point(event) { return previewPoint(preview, ref.current, event.clientX, event.clientY); }
  return <canvas ref={ref} width="720" height="430" className={`interactive-map ${readOnly ? 'read-only' : ''}`} onPointerDown={(event) => { if (!readOnly) dragStart.current = point(event); }} onPointerUp={(event) => { if (readOnly || !dragStart.current) return; const end = point(event); const start = dragStart.current; dragStart.current = null; onPose({ x: start.x, y: start.y, yaw: Math.atan2(end.y - start.y, end.x - start.x) }); }} />;
}

function drawTelemetryPath(ctx, preview, canvas, path, color) {
  if (!preview || !path?.points?.length) return;
  ctx.strokeStyle = color; ctx.lineWidth = 2; ctx.beginPath();
  path.points.forEach((point, index) => { const p = worldToCanvas(preview, canvas, point); if (index) ctx.lineTo(p.x, p.y); else ctx.moveTo(p.x, p.y); });
  ctx.stroke();
}

function drawPose(ctx, preview, canvas, pose, color) {
  if (!preview) return;
  const point = worldToCanvas(preview, canvas, pose);
  ctx.save(); ctx.translate(point.x, point.y); ctx.rotate(-(pose.yaw ?? 0)); ctx.fillStyle = color;
  ctx.beginPath(); ctx.moveTo(12, 0); ctx.lineTo(-8, 7); ctx.lineTo(-8, -7); ctx.closePath(); ctx.fill(); ctx.restore();
}

function worldToCanvas(preview, canvas, pose) {
  const yaw = preview.origin?.yaw ?? 0; const dx = pose.x - (preview.origin?.x ?? 0); const dy = pose.y - (preview.origin?.y ?? 0);
  const localX = Math.cos(yaw) * dx + Math.sin(yaw) * dy; const localY = -Math.sin(yaw) * dx + Math.cos(yaw) * dy;
  return { x: localX / (preview.width * preview.resolution) * canvas.width, y: canvas.height - localY / (preview.height * preview.resolution) * canvas.height };
}

function PoseEditor({ title, pose, onChange }) {
  return <div className="pose-editor"><strong>{title}</strong>{['x', 'y', 'yaw'].map((key) => <label key={key}>{key.toUpperCase()}<input type="number" step="0.01" value={pose[key]} onChange={(event) => onChange({ ...pose, [key]: Number(event.target.value) })} /></label>)}<small>在地图上按下并拖动以同时设置位置和朝向。</small></div>;
}

function RoutePointEditor({ point, label, onChange }) {
  return <fieldset className="route-point-editor"><legend>{label}</legend><input aria-label={`${label} 名称`} value={point.name} onChange={(event) => onChange({ ...point, name: event.target.value })} />{['x', 'y', 'yaw'].map((key) => <input key={key} aria-label={`${label} ${key}`} type="number" step="0.01" placeholder={key} value={point[key] ?? ''} onChange={(event) => onChange({ ...point, [key]: event.target.value })} />)}<input aria-label={`${label} 停留`} type="number" min="0" step="0.1" placeholder="停留秒" value={point.dwell_sec ?? ''} onChange={(event) => onChange({ ...point, dwell_sec: event.target.value })} /></fieldset>;
}

function MapList({ maps, selected, onSelect }) {
  return <aside className="map-list"><h3>托管地图</h3>{maps.length ? maps.map((map) => <button key={map.id} className={selected === map.id ? 'active' : ''} onClick={() => onSelect(map.id)}><span>{map.id}</span><small>{map.active ? '当前' : map.archived ? '归档' : map.complete ? '候选' : '不完整'}</small></button>) : <p>尚无托管地图</p>}</aside>;
}

function WorkbenchSidebar({ title, rows }) { return <aside className="workbench-sidebar"><h3>{title}</h3>{rows.map(([key, value]) => <div key={key}><span>{key}</span><strong>{value ?? '-'}</strong></div>)}</aside>; }
function LiveMapSummary({ telemetry }) { return <div className="live-map-summary"><h3>实时建图画布</h3><p>{telemetry?.map?.connected ? `已接收 /map：${telemetry.map.width} × ${telemetry.map.height}，分辨率 ${telemetry.map.resolution} m/cell` : '等待 Cartographer OccupancyGrid。现有地图监视器会持续显示真实 /map 图层。'}</p></div>; }
function Blockers({ items }) { return items?.length ? <div className="blocker-list"><strong>当前阻塞原因</strong><ul>{items.map((item) => <li key={item}>{item}</li>)}</ul></div> : <div className="ready-note">当前步骤门禁已满足</div>; }
function OperationStrip({ operation }) { return <div className={`operation-strip ${operation.status.toLowerCase()}`}><strong>{operation.type}</strong><span>{operation.step}</span><span>{operation.message}</span></div>; }
function MotionWarning({ onAcknowledge, busy }) { return <div className="motion-warning"><div><h3>首次运动风险确认</h3><p>导航、巡航、返航和非零遥控可能驱动物理车辆。请先清空周围区域，并确认急停可用。确认仅在本机私有配置中保存。</p><button className="primary-action" disabled={busy} onClick={onAcknowledge}>我已了解并确认</button></div></div>; }
function routePointValue(route, index) { return index === 0 ? route.home : route.waypoints[index - 1]; }
