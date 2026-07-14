export function sameOriginWebSocketUrl(pathname, location = window.location) {
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const path = pathname.startsWith('/') ? pathname : `/${pathname}`;
  return `${protocol}//${location.host}${path}`;
}
