import { API_BASE } from './config.js'

const REQUEST_TIMEOUT_MS = 15000

async function request(path, options = {}) {
  const controller = new AbortController()
  const timeoutMs = options.timeout ?? REQUEST_TIMEOUT_MS
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  const { timeout: _timeout, ...fetchOptions } = options
  let res
  try {
    res = await fetch(`${API_BASE}${path}`, {
      headers: { 'Content-Type': 'application/json', ...(fetchOptions.headers || {}) },
      signal: controller.signal,
      ...fetchOptions,
    })
  } catch (err) {
    if (err.name === 'AbortError') {
      throw new Error('请求超时，请确认后台服务已启动')
    }
    throw err
  } finally {
    clearTimeout(timer)
  }
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = body.error || body.detail?.error || JSON.stringify(body)
    } catch {
      /* ignore */
    }
    throw new Error(detail)
  }
  if (res.status === 204) return null
  return res.json()
}

export const api = {
  health: () => request('/api/health'),
  bootstrap: () => request('/api/bootstrap'),
  status: () => request('/api/status'),
  settings: () => request('/api/settings'),
  settingsDefaults: () => request('/api/settings/defaults'),
  secrets: () => request('/api/settings/secrets'),
  updateSettings: (body) => request('/api/settings', { method: 'PUT', body: JSON.stringify(body) }),
  updateDeepSeekKey: (apiKey) => request('/api/settings/deepseek-key', {
    method: 'PUT',
    body: JSON.stringify({ api_key: apiKey }),
  }),
  polishedStorage: () => request('/api/storage/polished'),
  clearPolishedStorage: () => request('/api/storage/polished/clear', { method: 'POST' }),
  logs: () => request('/api/logs'),
  logContent: (name, lines = 500) => request(`/api/logs/${encodeURIComponent(name)}?lines=${lines}`),
  activityLogs: (limit = 200) => request(`/api/logs/activity?limit=${limit}`),
  queue: (status) => request(status ? `/api/queue?status=${status}` : '/api/queue'),
  addQueue: (url, requestedRoute = 'auto') => request('/api/queue', {
    method: 'POST',
    body: JSON.stringify({ url, requested_route: requestedRoute }),
  }),
  deleteQueue: (id) => request(`/api/queue/${id}`, { method: 'DELETE' }),
  retryQueue: (id) => request(`/api/queue/${id}/retry`, { method: 'POST' }),
  reorderQueue: (ids) => request('/api/queue/reorder', { method: 'PATCH', body: JSON.stringify({ ids }) }),
  progress: (id) => request(`/api/queue/${id}/progress`),
  history: (params = {}) => {
    const q = new URLSearchParams()
    if (params.page) q.set('page', params.page)
    if (params.page_size) q.set('page_size', params.page_size)
    if (params.status) q.set('status', params.status)
    if (params.q) q.set('q', params.q)
    const qs = q.toString()
    return request(`/api/history${qs ? `?${qs}` : ''}`)
  },
  historyDetail: (id) => request(`/api/history/${id}`),
  deleteHistory: (id) => request(`/api/history/${id}`, { method: 'DELETE' }),
  retryHistoryPublish: (id) =>
    request(`/api/history/${id}/retry-publish`, { method: 'POST' }),
  historyChat: (id, messages) =>
    request(`/api/history/${id}/chat`, { method: 'POST', body: JSON.stringify({ messages }) }),
  async *historyChatStream(id, messages) {
    const res = await fetch(`${API_BASE}/api/history/${id}/chat/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages }),
    })
    if (!res.ok) {
      let detail = res.statusText
      try {
        const body = await res.json()
        detail = body.error || body.detail?.error || JSON.stringify(body)
      } catch {
        /* ignore */
      }
      throw new Error(detail)
    }
    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const parts = buffer.split('\n\n')
      buffer = parts.pop() || ''
      for (const part of parts) {
        const line = part.trim()
        if (!line.startsWith('data: ')) continue
        try {
          yield JSON.parse(line.slice(6))
        } catch {
          /* ignore malformed chunk */
        }
      }
    }
    const tail = buffer.trim()
    if (tail.startsWith('data: ')) {
      try {
        yield JSON.parse(tail.slice(6))
      } catch {
        /* ignore */
      }
    }
  },
}
