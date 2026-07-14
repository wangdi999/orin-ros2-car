import { sameOriginWebSocketUrl } from './browserUrl.js';

const AGENT_PREFIX = '/api/agent';

function errorMessage(payload, fallback) {
  if (typeof payload === 'string' && payload.trim()) return payload;
  if (payload?.detail) {
    return typeof payload.detail === 'string' ? payload.detail : JSON.stringify(payload.detail);
  }
  if (payload?.error) return payload.error;
  return fallback;
}

async function request(path, options = {}) {
  const headers = { ...(options.headers ?? {}) };
  if (options.body != null && !(options.body instanceof FormData)) {
    headers['content-type'] = headers['content-type'] ?? 'application/json';
  }

  const response = await fetch(`${AGENT_PREFIX}${path}`, {
    cache: 'no-store',
    ...options,
    headers
  });
  const contentType = response.headers.get('content-type') ?? '';
  const payload = contentType.includes('application/json')
    ? await response.json()
    : await response.text();
  if (!response.ok) {
    throw new Error(errorMessage(payload, `Agent API 请求失败（HTTP ${response.status}）`));
  }
  return payload;
}

function post(path, body = {}) {
  return request(path, {
    method: 'POST',
    body: JSON.stringify(body)
  });
}

export const agentApi = {
  health: () => request('/health'),
  locations: () => request('/locations'),
  robotStatus: () => request('/robot/status'),
  currentTask: () => request('/tasks/current'),
  task: (taskId) => request(`/tasks/${encodeURIComponent(taskId)}`),
  createRequest: (text) => post('/agent/requests', { text, user_id: 'web-console' }),
  parseMotion: (text) => post('/agent/motion/parse', { text, user_id: 'web-console' }),
  executeMotion: (intent, sourceText) => post('/agent/motion/execute', {
    intent,
    source_text: sourceText,
    confirmed: true,
    operator: 'web-console'
  }),
  transcribeSpeech: ({ audioBase64, audioFormat, language = 'zh-CN' }) => post(
    '/agent/speech/transcribe',
    {
      audio_base64: audioBase64,
      audio_format: audioFormat,
      language,
      user_id: 'web-console'
    }
  ),
  resumeThread: (threadId, decision, editedPlan = null) => post(
    `/agent/threads/${encodeURIComponent(threadId)}/resume`,
    {
      decision,
      operator: 'web-console',
      edited_plan: editedPlan
    }
  ),
  controlTask: (taskId, operation, reason) => post(
    `/tasks/${encodeURIComponent(taskId)}/${operation.toLowerCase()}`,
    { operator: 'web-console', reason }
  ),
  alarms: (filters = {}) => {
    const query = new URLSearchParams();
    Object.entries(filters).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== '') query.set(key, value);
    });
    const suffix = query.size ? `?${query}` : '';
    return request(`/alarms${suffix}`);
  },
  alarmSummary: () => request('/alarms/summary'),
  acknowledgeAlarm: (alarmId, note = '') => post(
    `/alarms/${encodeURIComponent(alarmId)}/acknowledge`,
    { operator: 'web-console', note }
  ),
  resolveAlarm: (alarmId, note = '') => post(
    `/alarms/${encodeURIComponent(alarmId)}/resolve`,
    { operator: 'web-console', note }
  ),
  createAlarm: (alarm) => post('/alarms', alarm),
  reports: () => request('/reports'),
  report: (reportId) => request(`/reports/${encodeURIComponent(reportId)}`),
  reportContent: (reportId) => request(`/reports/${encodeURIComponent(reportId)}/content`),
  generateReport: (taskId, title = '') => post('/reports/generate', {
    task_id: taskId || null,
    title: title || null,
    include_resolved: true,
    use_llm: true,
    operator: 'web-console'
  })
};

export function agentEventsUrl() {
  return sameOriginWebSocketUrl('/api/agent/events');
}
