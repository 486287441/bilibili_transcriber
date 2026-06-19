import { WS_URL } from './config.js'

export function createWsClient(onMessage, onStatus) {
  let ws = null
  let delay = 1000
  let stopped = false
  let reconnectTimer = null

  function connect() {
    if (stopped) return
    ws = new WebSocket(WS_URL)
    ws.onopen = () => {
      delay = 1000
      onStatus(true)
    }
    ws.onclose = () => {
      onStatus(false)
      scheduleReconnect()
    }
    ws.onerror = () => {
      ws?.close()
    }
    ws.onmessage = (ev) => {
      try {
        onMessage(JSON.parse(ev.data))
      } catch {
        /* ignore */
      }
    }
  }

  function scheduleReconnect() {
    if (stopped) return
    clearTimeout(reconnectTimer)
    reconnectTimer = setTimeout(() => {
      delay = Math.min(delay * 2, 30000)
      connect()
    }, delay)
  }

  function start() {
    stopped = false
    connect()
  }

  function stop() {
    stopped = true
    clearTimeout(reconnectTimer)
    ws?.close()
  }

  return { start, stop }
}
