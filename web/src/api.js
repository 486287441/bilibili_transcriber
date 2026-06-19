import { API_BASE } from './config.js'

async function request(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
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
  if (res.status === 204) return null
  return res.json()
}

export const api = {
  health: () => request('/api/health'),
  status: () => request('/api/status'),
  settings: () => request('/api/settings'),
  secrets: () => request('/api/settings/secrets'),
  updateSettings: (body) => request('/api/settings', { method: 'PUT', body: JSON.stringify(body) }),
  polishedStorage: () => request('/api/storage/polished'),
  clearPolishedStorage: () => request('/api/storage/polished/clear', { method: 'POST' }),
  autostart: () => request('/api/autostart'),
  enableAutostart: () => request('/api/autostart/enable', { method: 'POST' }),
  disableAutostart: () => request('/api/autostart/disable', { method: 'POST' }),
  logs: () => request('/api/logs'),
  logContent: (name, lines = 500) => request(`/api/logs/${encodeURIComponent(name)}?lines=${lines}`),
  queue: (status) => request(status ? `/api/queue?status=${status}` : '/api/queue'),
  addQueue: (url) => request('/api/queue', { method: 'POST', body: JSON.stringify({ url }) }),
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
  reprocessHistory: (id, mode = 'full') =>
    request(`/api/history/${id}/reprocess`, { method: 'POST', body: JSON.stringify({ mode }) }),
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
