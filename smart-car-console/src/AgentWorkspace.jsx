import { useCallback, useEffect, useMemo, useState } from 'react';
import { agentApi, agentEventsUrl } from './agentApi.js';
import './agentWorkspace.css';

const QUICK_PROMPTS = [
  '巡检东门和停车区，发现积水时立即暂停并通知我，最后返回起点',
  '按顺序巡检 A 栋、消防通道和西门，重点检查障碍物与路面坑洼',
  '执行一次短程安全巡检，只访问已启用地点，任务结束后生成报告'
];

const TASK_TERMINAL = new Set(['SUCCEEDED', 'FAILED', 'CANCELLED', 'REJECTED']);
const ALARM_STATUS_LABEL = {
  OPEN: '待处理',
  ACKNOWLEDGED: '已确认',
  RESOLVED: '已解决'
};
const SEVERITY_LABEL = {
  INFO: '提示',
  LOW: '低',
  MEDIUM: '中',
  HIGH: '高',
  CRITICAL: '严重'
};

export default function AgentWorkspace({ onClose, onEmergency, robotSnapshot, config }) {
  const [tab, setTab] = useState('mission');
  const [health, setHealth] = useState(null);
  const [locations, setLocations] = useState([]);
  const [robot, setRobot] = useState(null);
  const [currentTask, setCurrentTask] = useState(null);
  const [requestText, setRequestText] = useState(QUICK_PROMPTS[0]);
  const [requestResult, setRequestResult] = useState(null);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [events, setEvents] = useState([]);
  const [alarms, setAlarms] = useState([]);
  const [alarmSummary, setAlarmSummary] = useState({ total: 0, open: 0, acknowledged: 0, resolved: 0 });
  const [alarmStatus, setAlarmStatus] = useState('');
  const [alarmSeverity, setAlarmSeverity] = useState('');
  const [reports, setReports] = useState([]);
  const [selectedReport, setSelectedReport] = useState(null);
  const [reportContent, setReportContent] = useState('');

  const agentConfigured = config?.agent?.tokenSet !== false;
  const localEmergency = robotSnapshot?.runtime?.safety?.emergencyStopActive;

  const run = useCallback(async (label, action) => {
    setBusy(label);
    setError('');
    try {
      return await action();
    } catch (cause) {
      setError(cause?.message || String(cause));
      throw cause;
    } finally {
      setBusy('');
    }
  }, []);

  const refreshMission = useCallback(async () => {
    const [healthResult, locationResult, robotResult, taskResult] = await Promise.allSettled([
      agentApi.health(),
      agentApi.locations(),
      agentApi.robotStatus(),
      agentApi.currentTask()
    ]);
    if (healthResult.status === 'fulfilled') setHealth(healthResult.value);
    if (locationResult.status === 'fulfilled') setLocations(locationResult.value.items ?? []);
    if (robotResult.status === 'fulfilled') setRobot(robotResult.value);
    if (taskResult.status === 'fulfilled') setCurrentTask(taskResult.value.task ?? null);
    const firstFailure = [healthResult, locationResult, robotResult, taskResult]
      .find((item) => item.status === 'rejected');
    if (firstFailure) setError(firstFailure.reason?.message || 'Agent 状态读取失败');
  }, []);

  const refreshAlarms = useCallback(async () => {
    const filters = { status: alarmStatus, severity: alarmSeverity, limit: 100 };
    const [list, summary] = await Promise.all([agentApi.alarms(filters), agentApi.alarmSummary()]);
    setAlarms(list.items ?? []);
    setAlarmSummary(summary);
  }, [alarmSeverity, alarmStatus]);

  const refreshReports = useCallback(async () => {
    const result = await agentApi.reports();
    setReports(result.items ?? []);
  }, []);

  useEffect(() => {
    refreshMission().catch(() => {});
    refreshAlarms().catch(() => {});
    refreshReports().catch(() => {});
    const timer = setInterval(() => refreshMission().catch(() => {}), 6000);
    return () => clearInterval(timer);
  }, [refreshAlarms, refreshMission, refreshReports]);

  useEffect(() => {
    let closed = false;
    let retryTimer;
    let ws;
    const connect = () => {
      ws = new WebSocket(agentEventsUrl());
      ws.onmessage = (message) => {
        let parsed;
        try {
          parsed = JSON.parse(message.data);
        } catch {
          return;
        }
        setEvents((previous) => [parsed, ...previous].slice(0, 80));
        const type = parsed.type ?? '';
        if (type.includes('TASK') || type.includes('ROBOT') || type.includes('APPROVAL')) {
          refreshMission().catch(() => {});
        }
        if (type.includes('ALARM')) refreshAlarms().catch(() => {});
        if (type.includes('REPORT')) refreshReports().catch(() => {});
      };
      ws.onclose = () => {
        if (!closed) retryTimer = setTimeout(connect, 3000);
      };
      ws.onerror = () => ws.close();
    };
    connect();
    return () => {
      closed = true;
      clearTimeout(retryTimer);
      ws?.close();
    };
  }, [refreshAlarms, refreshMission, refreshReports]);

  const approval = requestResult?.status === 'AWAITING_APPROVAL'
    ? requestResult.interrupt
    : null;
  const plan = approval?.plan ?? null;
  const taskState = currentTask?.state ?? requestResult?.task_state ?? 'IDLE';
  const locationNames = useMemo(() => new Map(locations.map((item) => [item.id, item.name])), [locations]);

  async function submitNaturalLanguage() {
    const text = requestText.trim();
    if (!text) {
      setError('请输入巡检任务。');
      return;
    }
    const result = await run('create-request', () => agentApi.createRequest(text));
    setRequestResult(result);
    await refreshMission();
  }

  async function decide(decision) {
    if (!requestResult?.thread_id) return;
    const result = await run(`approval-${decision}`, () => (
      agentApi.resumeThread(requestResult.thread_id, decision)
    ));
    setRequestResult(result);
    await refreshMission();
  }

  async function controlTask(operation) {
    const taskId = currentTask?.id ?? currentTask?.task_id ?? requestResult?.task_id;
    if (!taskId) return;
    await run(`task-${operation}`, () => agentApi.controlTask(
      taskId,
      operation,
      `由控制台执行 ${operation}`
    ));
    await refreshMission();
  }

  async function updateAlarm(alarmId, operation) {
    await run(`alarm-${alarmId}`, () => (
      operation === 'acknowledge'
        ? agentApi.acknowledgeAlarm(alarmId)
        : agentApi.resolveAlarm(alarmId)
    ));
    await refreshAlarms();
  }

  async function generateReport() {
    const taskId = currentTask?.id ?? currentTask?.task_id ?? requestResult?.task_id ?? null;
    const generated = await run('report-generate', () => agentApi.generateReport(taskId));
    await refreshReports();
    if (generated?.id) await openReport(generated.id);
    setTab('reports');
  }

  async function openReport(reportId) {
    const [metadata, content] = await Promise.all([
      agentApi.report(reportId),
      agentApi.reportContent(reportId)
    ]);
    setSelectedReport(metadata);
    setReportContent(content);
  }

  function downloadReport() {
    if (!reportContent) return;
    const blob = new Blob([reportContent], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${selectedReport?.title || '巡检报告'}.md`;
    link.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="agent-workspace">
      <header className="agent-topbar">
        <div className="agent-heading">
          <button className="agent-back" onClick={onClose} type="button">← 返回遥控台</button>
          <div>
            <p>LANGGRAPH OPERATIONS</p>
            <h1>智能巡检任务中心</h1>
          </div>
        </div>
        <div className="agent-top-status">
          <StatusChip
            label="Agent"
            value={health?.ok ? '在线' : agentConfigured ? '连接中' : '未配置'}
            tone={health?.ok ? 'ok' : 'warn'}
          />
          <StatusChip
            label="机器人"
            value={robot?.gateway_online ? '可用' : '离线'}
            tone={robot?.gateway_online ? 'ok' : 'bad'}
          />
          <StatusChip
            label="任务"
            value={taskState}
            tone={TASK_TERMINAL.has(taskState) ? 'muted' : taskState === 'RUNNING' ? 'ok' : 'warn'}
          />
          <button className="agent-emergency" onClick={onEmergency} type="button">
            {localEmergency ? '急停已锁定' : '立即急停'}
          </button>
        </div>
      </header>

      <div className="agent-body">
        <aside className="agent-sidebar">
          <nav>
            <TabButton active={tab === 'mission'} onClick={() => setTab('mission')} badge={currentTask ? 1 : 0}>
              自然语言任务
            </TabButton>
            <TabButton active={tab === 'alarms'} onClick={() => setTab('alarms')} badge={alarmSummary.open ?? 0}>
              告警中心
            </TabButton>
            <TabButton active={tab === 'reports'} onClick={() => setTab('reports')} badge={reports.length}>
              巡检报告
            </TabButton>
          </nav>
          <section className="agent-side-card">
            <span>运行边界</span>
            <strong>LLM 不直接控制底盘</strong>
            <p>所有计划必须经过地点白名单、本地校验与人工确认。</p>
          </section>
          <section className="agent-side-card compact">
            <span>Agent 地址</span>
            <code>{config?.agent?.host || config?.car?.host || '未配置'}:{config?.agent?.port || 8100}</code>
          </section>
        </aside>

        <main className="agent-main">
          {error && (
            <div className="agent-error">
              <strong>操作失败</strong>
              <span>{error}</span>
              <button type="button" onClick={() => setError('')}>关闭</button>
            </div>
          )}
          {tab === 'mission' && (
            <MissionView
              requestText={requestText}
              setRequestText={setRequestText}
              submit={submitNaturalLanguage}
              busy={busy}
              plan={plan}
              approval={approval}
              requestResult={requestResult}
              decide={decide}
              locations={locationNames}
              currentTask={currentTask}
              taskState={taskState}
              controlTask={controlTask}
              events={events}
              robot={robot}
              generateReport={generateReport}
            />
          )}
          {tab === 'alarms' && (
            <AlarmView
              alarms={alarms}
              summary={alarmSummary}
              status={alarmStatus}
              severity={alarmSeverity}
              setStatus={setAlarmStatus}
              setSeverity={setAlarmSeverity}
              refresh={() => run('alarm-refresh', refreshAlarms)}
              updateAlarm={updateAlarm}
              busy={busy}
            />
          )}
          {tab === 'reports' && (
            <ReportView
              reports={reports}
              selected={selectedReport}
              content={reportContent}
              openReport={(id) => run(`report-${id}`, () => openReport(id))}
              generate={() => generateReport()}
              download={downloadReport}
              busy={busy}
            />
          )}
        </main>
      </div>
    </div>
  );
}

function MissionView({
  requestText,
  setRequestText,
  submit,
  busy,
  plan,
  approval,
  requestResult,
  decide,
  locations,
  currentTask,
  taskState,
  controlTask,
  events,
  robot,
  generateReport
}) {
  return (
    <div className="agent-view mission-view">
      <section className="agent-command-card">
        <div className="agent-section-heading">
          <div>
            <p>任务创建</p>
            <h2>用自然语言描述巡检目标</h2>
          </div>
          <span className="agent-model-pill">结构化计划 + 人工确认</span>
        </div>
        <textarea
          value={requestText}
          onChange={(event) => setRequestText(event.target.value)}
          placeholder="例如：巡检东门和停车区，发现积水时暂停并通知我，最后返回起点。"
          rows={5}
        />
        <div className="agent-quick-prompts">
          {QUICK_PROMPTS.map((prompt) => (
            <button key={prompt} type="button" onClick={() => setRequestText(prompt)}>
              {prompt}
            </button>
          ))}
        </div>
        <div className="agent-command-actions">
          <span>系统只允许使用已登记并启用的命名地点。</span>
          <button className="agent-primary" disabled={Boolean(busy)} onClick={submit} type="button">
            {busy === 'create-request' ? '正在生成计划…' : '生成巡检计划'}
          </button>
        </div>
      </section>

      <div className="agent-mission-grid">
        <section className="agent-panel">
          <div className="agent-section-heading small">
            <div>
              <p>计划审批</p>
              <h2>{plan ? plan.name : '等待任务输入'}</h2>
            </div>
            <StateBadge state={requestResult?.status || 'DRAFT'} />
          </div>
          {!plan && <EmptyState title="尚未生成计划" detail="提交自然语言任务后，本地校验通过的计划会显示在这里。" />}
          {plan && (
            <>
              <p className="agent-plan-summary">{plan.summary || '未提供计划摘要'}</p>
              <div className="agent-waypoints">
                {(plan.waypoints ?? []).map((waypoint, index) => (
                  <div key={`${waypoint}-${index}`}>
                    <span>{index + 1}</span>
                    <strong>{locations.get(waypoint) || waypoint}</strong>
                    <code>{waypoint}</code>
                  </div>
                ))}
              </div>
              <div className="agent-policy-grid">
                <InfoCell label="异常策略" value={formatPolicy(plan.event_policy)} />
                <InfoCell label="任务结束" value={plan.return_home ? '返回起点' : '停留在终点'} />
                <InfoCell label="导航状态" value={robot?.nav2_ready ? 'Nav2 就绪' : 'Nav2 未就绪'} />
                <InfoCell label="急停状态" value={robot?.emergency_stopped ? '已锁定' : '未触发'} />
              </div>
              {(approval?.warnings ?? []).length > 0 && (
                <div className="agent-warning-list">
                  {(approval.warnings ?? []).map((warning) => <span key={warning}>{warning}</span>)}
                </div>
              )}
              {requestResult?.status === 'AWAITING_APPROVAL' && (
                <div className="agent-approval-actions">
                  <button type="button" onClick={() => decide('REJECT')} disabled={Boolean(busy)}>拒绝计划</button>
                  <button className="agent-primary" type="button" onClick={() => decide('APPROVE')} disabled={Boolean(busy)}>
                    {busy === 'approval-APPROVE' ? '正在提交…' : '确认并启动'}
                  </button>
                </div>
              )}
            </>
          )}
        </section>

        <section className="agent-panel">
          <div className="agent-section-heading small">
            <div>
              <p>当前任务</p>
              <h2>{currentTask?.name || currentTask?.plan?.name || '暂无运行任务'}</h2>
            </div>
            <StateBadge state={taskState} />
          </div>
          {!currentTask && !requestResult?.task_id && (
            <EmptyState title="任务队列为空" detail="已确认的巡检任务会在此显示状态和控制操作。" />
          )}
          {(currentTask || requestResult?.task_id) && (
            <>
              <dl className="agent-task-details">
                <div><dt>任务 ID</dt><dd>{currentTask?.id || currentTask?.task_id || requestResult?.task_id}</dd></div>
                <div><dt>当前状态</dt><dd>{taskState}</dd></div>
                <div><dt>当前位置</dt><dd>{robot?.current_location_id || '未知'}</dd></div>
                <div><dt>航点进度</dt><dd>{Number(robot?.current_waypoint_index ?? 0) + 1}</dd></div>
              </dl>
              <div className="agent-task-actions">
                <button type="button" onClick={() => controlTask('PAUSE')} disabled={taskState !== 'RUNNING' || Boolean(busy)}>暂停</button>
                <button type="button" onClick={() => controlTask('RESUME')} disabled={taskState !== 'PAUSED' || Boolean(busy)}>继续</button>
                <button type="button" onClick={() => controlTask('CANCEL')} disabled={TASK_TERMINAL.has(taskState) || Boolean(busy)}>取消</button>
                <button className="agent-primary" type="button" onClick={generateReport} disabled={!TASK_TERMINAL.has(taskState) || Boolean(busy)}>生成报告</button>
              </div>
            </>
          )}
        </section>
      </div>

      <section className="agent-panel agent-timeline-panel">
        <div className="agent-section-heading small">
          <div><p>事件流</p><h2>工作流与机器人事件</h2></div>
          <span>{events.length} 条</span>
        </div>
        <div className="agent-event-list">
          {events.length === 0 && <EmptyState title="尚无事件" detail="Agent WebSocket 事件将在这里实时显示。" />}
          {events.map((event, index) => (
            <article key={event.event_id || `${event.type}-${index}`}>
              <i className={`event-dot ${eventTone(event.type)}`} />
              <div>
                <strong>{event.type || 'UNKNOWN_EVENT'}</strong>
                <span>{formatEventText(event)}</span>
              </div>
              <time>{formatDate(event.created_at || event.timestamp)}</time>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}

function AlarmView({ alarms, summary, status, severity, setStatus, setSeverity, refresh, updateAlarm, busy }) {
  return (
    <div className="agent-view alarm-view">
      <div className="agent-summary-grid">
        <SummaryCard label="告警总数" value={summary.total ?? 0} tone="neutral" />
        <SummaryCard label="待处理" value={summary.open ?? 0} tone="bad" />
        <SummaryCard label="已确认" value={summary.acknowledged ?? 0} tone="warn" />
        <SummaryCard label="已解决" value={summary.resolved ?? 0} tone="ok" />
      </div>
      <section className="agent-panel">
        <div className="agent-section-heading small">
          <div><p>安全事件</p><h2>告警处理队列</h2></div>
          <div className="agent-filters">
            <select value={status} onChange={(event) => setStatus(event.target.value)}>
              <option value="">全部状态</option>
              <option value="OPEN">待处理</option>
              <option value="ACKNOWLEDGED">已确认</option>
              <option value="RESOLVED">已解决</option>
            </select>
            <select value={severity} onChange={(event) => setSeverity(event.target.value)}>
              <option value="">全部等级</option>
              {Object.entries(SEVERITY_LABEL).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
            </select>
            <button type="button" onClick={refresh} disabled={Boolean(busy)}>刷新</button>
          </div>
        </div>
        <div className="agent-alarm-list">
          {alarms.length === 0 && <EmptyState title="没有匹配的告警" detail="YOLO 或其他安全节点产生的结构化事件会进入该队列。" />}
          {alarms.map((alarm) => (
            <article className={`agent-alarm-card severity-${String(alarm.severity).toLowerCase()}`} key={alarm.id}>
              <div className="alarm-main">
                <div className="alarm-title-row">
                  <SeverityBadge severity={alarm.severity} />
                  <strong>{alarm.description || categoryLabel(alarm.category)}</strong>
                  <StateBadge state={alarm.status} />
                </div>
                <p>{categoryLabel(alarm.category)} · 置信度 {formatConfidence(alarm.confidence)}</p>
                <div className="alarm-meta">
                  <span>位置：{alarm.location_id || '未知'}</span>
                  <span>任务：{alarm.task_id || '未关联'}</span>
                  <span>发生时间：{formatDate(alarm.occurred_at)}</span>
                </div>
                {alarm.evidence_url && <a href={alarm.evidence_url} target="_blank" rel="noreferrer">查看证据图像</a>}
              </div>
              <div className="alarm-actions">
                <button
                  type="button"
                  onClick={() => updateAlarm(alarm.id, 'acknowledge')}
                  disabled={alarm.status !== 'OPEN' || Boolean(busy)}
                >确认</button>
                <button
                  className="agent-primary"
                  type="button"
                  onClick={() => updateAlarm(alarm.id, 'resolve')}
                  disabled={alarm.status === 'RESOLVED' || Boolean(busy)}
                >标记解决</button>
              </div>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}

function ReportView({ reports, selected, content, openReport, generate, download, busy }) {
  return (
    <div className="agent-view report-view">
      <section className="agent-panel report-list-panel">
        <div className="agent-section-heading small">
          <div><p>归档</p><h2>巡检报告</h2></div>
          <button className="agent-primary" type="button" onClick={generate} disabled={Boolean(busy)}>
            {busy === 'report-generate' ? '生成中…' : '生成新报告'}
          </button>
        </div>
        <div className="agent-report-list">
          {reports.length === 0 && <EmptyState title="暂无报告" detail="任务结束后可基于任务信息和告警记录生成 Markdown 报告。" />}
          {reports.map((report) => (
            <button
              type="button"
              key={report.id}
              className={selected?.id === report.id ? 'selected' : ''}
              onClick={() => openReport(report.id)}
            >
              <strong>{report.title}</strong>
              <span>{report.task_id || '综合报告'}</span>
              <small>{formatDate(report.created_at)} · {report.alarm_count ?? 0} 个告警</small>
            </button>
          ))}
        </div>
      </section>
      <section className="agent-panel report-preview-panel">
        <div className="agent-section-heading small">
          <div><p>预览</p><h2>{selected?.title || '选择一份报告'}</h2></div>
          <button type="button" onClick={download} disabled={!content}>下载 Markdown</button>
        </div>
        {content
          ? <pre className="agent-report-content">{content}</pre>
          : <EmptyState title="未选择报告" detail="从左侧列表选择报告后，可在此查看和下载完整内容。" />}
      </section>
    </div>
  );
}

function TabButton({ active, onClick, badge, children }) {
  return (
    <button className={active ? 'active' : ''} type="button" onClick={onClick}>
      <span>{children}</span>
      {badge > 0 && <b>{badge}</b>}
    </button>
  );
}

function StatusChip({ label, value, tone }) {
  return <div className={`agent-status-chip ${tone}`}><span>{label}</span><strong>{value}</strong></div>;
}

function StateBadge({ state }) {
  const normalized = String(state || 'UNKNOWN').toUpperCase();
  const tone = normalized === 'RUNNING' || normalized === 'SUCCEEDED' || normalized === 'RESOLVED'
    ? 'ok'
    : normalized.includes('FAIL') || normalized === 'REJECTED' || normalized === 'CRITICAL'
      ? 'bad'
      : normalized === 'OPEN' || normalized.includes('WAIT') || normalized === 'PAUSED'
        ? 'warn'
        : 'muted';
  return <span className={`agent-state-badge ${tone}`}>{ALARM_STATUS_LABEL[normalized] || normalized}</span>;
}

function SeverityBadge({ severity }) {
  const value = String(severity || 'MEDIUM').toUpperCase();
  return <span className={`agent-severity severity-${value.toLowerCase()}`}>{SEVERITY_LABEL[value] || value}</span>;
}

function SummaryCard({ label, value, tone }) {
  return <section className={`agent-summary-card ${tone}`}><span>{label}</span><strong>{value}</strong></section>;
}

function InfoCell({ label, value }) {
  return <div><span>{label}</span><strong>{value}</strong></div>;
}

function EmptyState({ title, detail }) {
  return <div className="agent-empty"><strong>{title}</strong><span>{detail}</span></div>;
}

function formatPolicy(policy) {
  if (!policy || Object.keys(policy).length === 0) return '默认规则';
  return Object.entries(policy).map(([key, value]) => `${categoryLabel(key)}：${value}`).join('；');
}

function categoryLabel(value) {
  const labels = {
    flooding: '路面积水',
    pothole: '路面坑洼',
    obstacle: '道路障碍物',
    person: '人员进入',
    fire: '烟火异常'
  };
  return labels[String(value).toLowerCase()] || value || '未知类型';
}

function formatConfidence(value) {
  const number = Number(value);
  return Number.isFinite(number) ? `${(number * 100).toFixed(1)}%` : '未知';
}

function formatDate(value) {
  if (!value) return '刚刚';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString('zh-CN', { hour12: false });
}

function formatEventText(event) {
  const data = event.data ?? {};
  return data.response || data.message || data.task_state || data.state || data.description || '状态已更新';
}

function eventTone(type = '') {
  if (type.includes('FAILED') || type.includes('STOPPED') || type.includes('ALARM')) return 'bad';
  if (type.includes('SUCCEEDED') || type.includes('RESOLVED') || type.includes('CLEARED')) return 'ok';
  return 'warn';
}
