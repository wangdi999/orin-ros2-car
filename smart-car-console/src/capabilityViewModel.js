export function visibleCapabilityItems(capabilities = {}) {
  return Object.values(capabilities.items ?? {}).filter((item) => !(
    item.availability === 'UNSUPPORTED' && capabilities.stale !== true
  ));
}

export function capabilityUiState(item = {}) {
  const availability = {
    SUPPORTED: '已具备', UNSUPPORTED: '不支持', UNKNOWN: '待确认'
  }[item.availability] ?? item.availability ?? '待确认';
  const runtime = {
    ACTIVE: '运行中', INACTIVE: '未运行', STALE: '证据过期', ERROR: '探测失败'
  }[item.runtime] ?? item.runtime ?? '待确认';
  return {
    availability,
    runtime,
    disabled: item.safety === 'BLOCKED',
    reason: item.blockedReason ?? item.reason ?? null
  };
}
