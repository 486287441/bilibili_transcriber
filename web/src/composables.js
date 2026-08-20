import { onUnmounted, ref, watch } from 'vue'

const PHASES = ['download', 'transcribe', 'polish']

function phaseTargetFromProgress(progress, phase) {
  if (!progress?.phase) return 0
  const cur = PHASES.indexOf(progress.phase)
  const idx = PHASES.indexOf(phase)
  if (cur < 0 || idx < 0) return 0
  if (idx < cur) return 100
  if (idx > cur) return 0
  return Math.min(100, Math.max(0, progress.phase_progress ?? 0))
}

/** Three independent phase bars, each 0→100 before the next starts. */
export function useSmoothPhaseProgress(progressRef) {
  const download = ref(0)
  const transcribe = ref(0)
  const polish = ref(0)
  const displays = { download, transcribe, polish }

  const barState = PHASES.map(() => ({
    lastTarget: 0,
    lastTargetAt: 0,
    velocity: 0,
  }))
  const targets = { download: 0, transcribe: 0, polish: 0 }
  let frame = null

  function resetBar(i) {
    barState[i] = { lastTarget: 0, lastTargetAt: 0, velocity: 0 }
  }

  watch(progressRef, (p) => {
    if (!p) {
      PHASES.forEach((ph, i) => {
        targets[ph] = 0
        resetBar(i)
        displays[ph].value = 0
      })
      if (frame != null) {
        cancelAnimationFrame(frame)
        frame = null
      }
      return
    }
    const now = performance.now()
    PHASES.forEach((ph, i) => {
      const v = phaseTargetFromProgress(p, ph)
      const s = barState[i]
      if (s.lastTargetAt > 0) {
        const dt = (now - s.lastTargetAt) / 1000
        if (dt > 0.01) {
          const measured = (v - s.lastTarget) / dt
          s.velocity = s.velocity * 0.4 + measured * 0.6
        }
      }
      s.lastTarget = v
      s.lastTargetAt = now
      targets[ph] = v
    })
    if (frame == null) frame = requestAnimationFrame(tick)
  })

  function tick() {
    const now = performance.now()
    let anyMoving = false
    PHASES.forEach((ph, i) => {
      const s = barState[i]
      const dt = (now - s.lastTargetAt) / 1000
      let goal = s.lastTarget + s.velocity * dt
      const target = targets[ph]
      if (target >= 100) {
        goal = 100
      } else if (goal > 99.5) {
        goal = 99.5
      }
      goal = Math.max(goal, displays[ph].value)

      const diff = goal - displays[ph].value
      if (Math.abs(diff) < 0.02 && Math.abs(target - displays[ph].value) < 0.05) {
        displays[ph].value = target
      } else {
        displays[ph].value += diff * 0.15
        anyMoving = true
      }
    })
    frame = anyMoving ? requestAnimationFrame(tick) : null
  }

  onUnmounted(() => {
    if (frame != null) cancelAnimationFrame(frame)
  })

  return { download, transcribe, polish }
}

/** ETA display with monotonic smoothing (decrease freely, increase capped at +5s). */
export function useSmoothEta(progressRef) {
  const displayEta = ref(0)

  watch(
    () => progressRef.value?.eta_seconds,
    (raw) => {
      if (raw == null || raw === undefined) {
        displayEta.value = 0
        return
      }
      const next = Math.max(0, Math.round(raw))
      const prev = displayEta.value
      if (prev === 0 || next <= prev) {
        displayEta.value = next
      } else {
        displayEta.value = Math.min(next, prev + 5)
      }
    },
  )

  return { displayEta }
}

/** Compact top-bar progress while the ASR model loads (history-based ETA). */
export function useModelLoadProgress(statusRef) {
  const display = ref(0)
  const visible = ref(false)
  let frame = null
  let localStartAt = 0
  let etaSec = 45
  let hideTimer = null

  function stopFrame() {
    if (frame != null) {
      cancelAnimationFrame(frame)
      frame = null
    }
  }

  function clearHideTimer() {
    if (hideTimer != null) {
      clearTimeout(hideTimer)
      hideTimer = null
    }
  }

  function tick() {
    const elapsed = (performance.now() - localStartAt) / 1000
    const est = Math.max(etaSec, 8)
    let pct = 100 * (1 - Math.exp(-elapsed / est))
    pct = Math.min(pct, 95)
    display.value = Math.max(display.value, pct)
    frame = requestAnimationFrame(tick)
  }

  function beginLoading(s) {
    clearHideTimer()
    const elapsed = Number(s.model_load_elapsed_seconds) || 0
    etaSec = Number(s.model_load_eta_seconds) || 45
    localStartAt = performance.now() - elapsed * 1000
    visible.value = true
    if (display.value <= 0) display.value = 0
    stopFrame()
    frame = requestAnimationFrame(tick)
  }

  function finishLoading() {
    stopFrame()
    display.value = 100
    hideTimer = setTimeout(() => {
      visible.value = false
      display.value = 0
      hideTimer = null
    }, 500)
  }

  watch(statusRef, (s, prev) => {
    if (s.model_loading) {
      if (!prev?.model_loading) {
        beginLoading(s)
      } else if (s.model_load_elapsed_seconds != null) {
        const elapsed = Number(s.model_load_elapsed_seconds) || 0
        etaSec = Number(s.model_load_eta_seconds) || etaSec
        localStartAt = performance.now() - elapsed * 1000
      }
      return
    }
    if (prev?.model_loading) {
      if (s.model_loaded) {
        finishLoading()
      } else {
        clearHideTimer()
        stopFrame()
        visible.value = false
        display.value = 0
      }
    }
  })

  onUnmounted(() => {
    stopFrame()
    clearHideTimer()
  })

  return { display, visible }
}

export function formatEta(seconds, phase) {
  const s = Math.max(0, Math.round(seconds || 0))
  if (phase === 'transcribe') {
    const lowMin = Math.max(1, Math.floor((s * 0.75) / 60))
    const highMin = Math.max(lowMin, Math.ceil((s * 1.5) / 60))
    if (highMin <= 1) return '预计还需约 1 分钟'
    if (lowMin === highMin) return `预计还需约 ${lowMin} 分钟`
    return `预计还需约 ${lowMin}~${highMin} 分钟`
  }
  const m = Math.floor(s / 60)
  const r = s % 60
  return `预计剩余 ${m} 分 ${r} 秒`
}

export const PHASE_LABELS = {
  download: '下载',
  transcribe: '转录',
  polish: '润色',
}

export const STATUS_LABELS = {
  pending: '等待中',
  downloading: '下载中',
  transcribing: '转录中',
  polishing: '润色中',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
}

export const TRANSCRIPTION_ROUTE_OPTIONS = [
  { value: 'auto', label: '官方字幕优先' },
  { value: 'subtitle', label: 'B站字幕' },
  { value: 'ocr', label: '画面 OCR' },
  { value: 'asr', label: '语音识别' },
]

export const TRANSCRIPTION_ROUTE_LABELS = Object.fromEntries(
  TRANSCRIPTION_ROUTE_OPTIONS.map((item) => [item.value, item.label]),
)

/** Resolve the physical transcription route, with ASR as the legacy-data fallback. */
export function effectiveTranscriptionRoute(item) {
  const resolved = item?.resolved_route
  if (resolved && resolved !== 'auto') return resolved

  const requested = item?.requested_route
  if (requested && requested !== 'auto') return requested

  const hasRouteFields = item && (
    Object.prototype.hasOwnProperty.call(item, 'requested_route') ||
    Object.prototype.hasOwnProperty.call(item, 'resolved_route')
  )
  return hasRouteFields ? null : 'asr'
}

export function transcriptionRouteLabel(item) {
  const route = effectiveTranscriptionRoute(item)
  if (item?.requested_route === 'auto') {
    return route ? `字幕优先 · ${TRANSCRIPTION_ROUTE_LABELS[route] || route}` : '正在检测字幕'
  }
  return TRANSCRIPTION_ROUTE_LABELS[route] || TRANSCRIPTION_ROUTE_LABELS[item?.requested_route] || '正在检测字幕'
}

export function transcriptionPhaseLabel(item) {
  const route = effectiveTranscriptionRoute(item)
  if (route === 'subtitle') return '字幕提取'
  if (route === 'ocr') return '画面 OCR'
  if (route === 'asr') return '语音转写'
  return '字幕检测'
}

const SITE_HINTS = [
  ['bilibili', ['bilibili.com', 'b23.tv']],
  ['youtube', ['youtube.com', 'youtu.be']],
  ['douyin', ['douyin.com', 'iesdouyin.com']],
]

export const SITE_LABELS = {
  bilibili: '哔哩哔哩',
  youtube: 'YouTube',
  douyin: '抖音',
  generic: '其它',
}

export function detectSiteFromUrl(url) {
  const lowered = (url || '').toLowerCase()
  for (const [site, hints] of SITE_HINTS) {
    if (hints.some((hint) => lowered.includes(hint))) return site
  }
  return 'generic'
}

export function siteLabelFor(item) {
  const key = item?.site && SITE_LABELS[item.site] ? item.site : detectSiteFromUrl(item?.url)
  return SITE_LABELS[key] || key
}

/** Brief failure reason for queue/history rows. */
export function summarizeError(message) {
  if (!message) return ''
  const msg = String(message).trim()
  if (!msg) return ''
  const lower = msg.toLowerCase()

  if (msg === '转写失败' || msg === '下载音频失败' || msg === '发布失败（已执行回退流程）') return msg
  if (msg.includes('412') || lower.includes('precondition failed')) return 'B站 Cookie 失效，请重新导出'
  if (msg.includes('403') || lower.includes('sign in')) return '需要登录或无权访问'
  if (lower.includes('unexpected_eof') || (lower.includes('ssl') && lower.includes('eof'))) {
    return '下载时网络连接中断'
  }
  if (lower.includes('timed out') || lower.includes('timeout') || msg.includes('10060')) return '网络超时'
  if (lower.includes('errno 22')) return '下载异常，请重试'
  if (lower.includes('unable to download') || lower.includes('[download] got error')) {
    if (lower.includes('ssl') || lower.includes('unexpected_eof')) return '下载时网络连接中断'
    if (lower.includes('errno 22')) return '下载异常，请重试'
    return '视频下载失败'
  }
  if (lower.includes('is not defined')) return '程序内部错误'
  if (msg.length <= 32) return msg
  return `${msg.slice(0, 28)}…`
}

export function taskFailReason(item) {
  return item?.error_summary || summarizeError(item?.error_message)
}
