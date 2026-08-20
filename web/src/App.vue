<template>
  <div class="app" :class="{ 'is-loading': appLoading }">
    <div v-if="appLoading" class="app-loading-overlay" role="status" aria-live="polite">
      <div class="app-loading-card">
        <span class="app-loading-spinner" aria-hidden="true" />
        <span class="app-loading-text">加载中…</span>
        <span class="app-loading-hint">正在连接服务并同步数据</span>
      </div>
    </div>

    <header class="topbar">
      <div class="brand-block">
        <div class="brand">视频转文稿助手</div>
      </div>
      <div class="status">
        <span class="dot" :class="wsConnected ? 'ok' : 'err'" />
        {{ wsConnected ? '运行中' : '未连接' }}
      </div>
      <button type="button" class="ghost" @click="openSettings">设置</button>
    </header>

    <main class="layout">
      <QueuePanel
        :items="queueItems"
        @delete="onDeleteQueue"
        @retry="onRetryQueue"
        @reorder="onReorderQueue"
      />
      <ProgressPanel
        :active="activeTask"
        :progress="currentProgress"
      />
    </main>

    <HistoryPanel
      :items="historyItems"
      :total="historyTotal"
      :page="historyPage"
      :publish-retrying-ids="publishRetrying"
      @search="onHistorySearch"
      @page="onHistoryPage"
      @delete="onDeleteHistory"
      @retry-publish="onRetryPublish"
    />

    <div v-if="notice" class="app-notice" role="status" aria-live="polite">
      {{ notice }}
    </div>

    <SettingsDialog
      ref="settingsRef"
      :settings="settings"
      :secrets="secrets"
      @refresh="loadSettingsBundle"
    />
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { api } from './api.js'
import { useModelLoadProgress } from './composables.js'
import { createWsClient } from './ws.js'
import HistoryPanel from './components/HistoryPanel.vue'
import ProgressPanel from './components/ProgressPanel.vue'
import QueuePanel from './components/QueuePanel.vue'
import SettingsDialog from './components/SettingsDialog.vue'

const wsConnected = ref(false)
const appLoading = ref(true)
const queueItems = ref([])
const settings = ref({
  clipboard_enabled: true,
  auto_open_feishu: false,
  model_idle_timeout_minutes: 30,
  deepseek_model: 'deepseek-v4-pro',
  auto_fallback_route: 'asr',
  second_stage_enabled: true,
})
const secrets = ref({})
const serviceStatus = ref({ model_loaded: false, model_loading: false })
const { display: modelLoadDisplay, visible: modelLoadVisible } = useModelLoadProgress(serviceStatus)
const currentProgress = ref(null)
const historyItems = ref([])
const historyTotal = ref(0)
const historyPage = ref(1)
const historyQuery = ref('')
const settingsRef = ref(null)
const publishRetrying = ref(new Set())
const deletingQueueIds = ref(new Set())
const notice = ref('')

const ACTIVE = new Set(['downloading', 'transcribing', 'polishing'])

const activeTask = computed(() =>
  queueItems.value.find((t) => ACTIVE.has(t.status)) ||
  queueItems.value.find((t) => t.status === 'pending') ||
  null,
)

const modelStatus = computed(() => {
  const s = serviceStatus.value
  if (s.model_loading) {
    return {
      text: '模型加载中…',
      variant: 'busy',
      title: 'Fun-ASR-Nano 正在载入显存',
    }
  }
  if (s.model_loaded) {
    const sec = s.will_sleep_in_seconds
    if (sec != null && sec > 0) {
      if (sec >= 60) {
        const m = Math.ceil(sec / 60)
        return {
          text: `模型已加载 · ${m} 分钟后休眠`,
          variant: 'ok',
          title: '转录模型已在显存中',
        }
      }
      return {
        text: `模型已加载 · ${sec} 秒后休眠`,
        variant: 'ok',
        title: '转录模型已在显存中',
      }
    }
    return { text: '模型已加载', variant: 'ok', title: '转录模型已在显存中' }
  }
  return {
    text: '模型未加载（空闲）',
    variant: 'muted',
    title: '后台服务在运行；转录模型未载入显存（正常）',
  }
})

let wsClient = null
let statusTimer = null
let noticeTimer = null

function showNotice(message) {
  notice.value = message
  if (noticeTimer != null) clearTimeout(noticeTimer)
  noticeTimer = setTimeout(() => {
    notice.value = ''
    noticeTimer = null
  }, 2600)
}

function scheduleStatusPoll(loading = false) {
  if (statusTimer != null) clearTimeout(statusTimer)
  statusTimer = setTimeout(pollStatus, loading ? 2000 : 30000)
}

function pollStatus() {
  if (!wsConnected.value) return
  api.status()
    .then((s) => {
      serviceStatus.value = s
      scheduleStatusPoll(s.model_loading)
    })
    .catch(() => scheduleStatusPoll(false))
}

async function refreshQueue() {
  applyQueueItems(await api.queue())
  await syncProgress()
}

function applyQueueItems(items) {
  const existingIds = new Set(items.map((item) => item.id))
  const hidden = new Set(deletingQueueIds.value)
  for (const id of hidden) {
    if (!existingIds.has(id)) hidden.delete(id)
  }
  deletingQueueIds.value = hidden
  queueItems.value = items.filter((item) => !hidden.has(item.id))
}

async function syncProgress() {
  const active = queueItems.value.find((t) => ACTIVE.has(t.status))
  if (!active) {
    currentProgress.value = null
    return
  }
  try {
    const snap = await api.progress(active.id)
    currentProgress.value = snap
  } catch {
    /* ignore */
  }
}

async function loadSettingsBundle() {
  ;[settings.value, secrets.value, serviceStatus.value] = await Promise.all([
    api.settings(),
    api.secrets(),
    api.status(),
  ])
}

async function refreshHistory() {
  const data = await api.history({
    page: historyPage.value,
    page_size: 20,
    q: historyQuery.value || undefined,
  })
  historyItems.value = data.items
  historyTotal.value = data.total
}

function handleWs(msg) {
  if (msg.type === 'task.progress') {
    if (deletingQueueIds.value.has(msg.payload?.task_id)) return
    currentProgress.value = msg.payload
    return
  }
  if (
    msg.type === 'queue.updated' ||
    msg.type === 'task.state_changed' ||
    msg.type === 'task.route_resolved'
  ) {
    refreshQueue()
    if (msg.type === 'task.state_changed' && msg.payload?.new_status === 'completed') {
      refreshHistory()
    }
    return
  }
  if (msg.type === 'task.metadata_ready') {
    refreshQueue()
    return
  }
  if (msg.type === 'settings.changed') {
    loadSettingsBundle()
    return
  }
  if (
    msg.type === 'model.loading' ||
    msg.type === 'model.loaded' ||
    msg.type === 'model.unloaded' ||
    msg.type === 'service.state'
  ) {
    api.status().then((s) => {
      serviceStatus.value = s
      scheduleStatusPoll(s.model_loading)
    })
    return
  }
  if (
    msg.type === 'history.created' ||
    msg.type === 'history.deleted' ||
    msg.type === 'history.publish_updated'
  ) {
    refreshHistory()
    return
  }
}

async function onDeleteQueue(id) {
  const backup = queueItems.value
  deletingQueueIds.value = new Set(deletingQueueIds.value).add(id)
  queueItems.value = queueItems.value.filter((t) => t.id !== id)
  if (currentProgress.value?.task_id === id) {
    currentProgress.value = null
  }
  try {
    const result = await api.deleteQueue(id)
    showNotice(result.status === 'cancel_requested' ? '正在取消并清理任务' : '任务已删除')
    await refreshQueue()
    const hidden = new Set(deletingQueueIds.value)
    hidden.delete(id)
    deletingQueueIds.value = hidden
  } catch (e) {
    const hidden = new Set(deletingQueueIds.value)
    hidden.delete(id)
    deletingQueueIds.value = hidden
    queueItems.value = backup
    await refreshQueue()
    alert(e.message || '删除失败')
  }
}

async function onRetryQueue(id) {
  await api.retryQueue(id)
  await refreshQueue()
}

async function onReorderQueue(fromIdx, toIdx) {
  const ids = queueItems.value.map((t) => t.id)
  const [moved] = ids.splice(fromIdx, 1)
  ids.splice(toIdx, 0, moved)
  await api.reorderQueue(ids)
  await refreshQueue()
}

async function onHistorySearch(q) {
  historyQuery.value = q
  historyPage.value = 1
  await refreshHistory()
}

async function onHistoryPage(p) {
  historyPage.value = p
  await refreshHistory()
}

async function onDeleteHistory(id) {
  await api.deleteHistory(id)
  await refreshHistory()
}

async function onRetryPublish(id) {
  if (publishRetrying.value.has(id)) return
  publishRetrying.value = new Set(publishRetrying.value).add(id)
  try {
    await api.retryHistoryPublish(id)
    showNotice('已重新加入飞书后台发布队列')
    await refreshHistory()
  } catch (e) {
    showNotice(e.message || '重试飞书发布失败')
  } finally {
    const next = new Set(publishRetrying.value)
    next.delete(id)
    publishRetrying.value = next
  }
}

function openSettings() {
  settingsRef.value?.open()
}

async function loadInitialData() {
  try {
    const data = await api.bootstrap()
    applyQueueItems(data.queue ?? [])
    settings.value = data.settings
    secrets.value = data.secrets
    serviceStatus.value = data.status
    historyItems.value = data.history?.items ?? []
    historyTotal.value = data.history?.total ?? 0
    await syncProgress()
  } catch {
    await Promise.allSettled([
      refreshQueue(),
      loadSettingsBundle(),
      refreshHistory(),
    ])
  }
}

onMounted(async () => {
  appLoading.value = true
  try {
    await loadInitialData()
  } finally {
    appLoading.value = false
  }

  wsClient = createWsClient(handleWs, (ok) => {
    wsConnected.value = ok
    if (ok) {
      loadInitialData()
      pollStatus()
    }
  })
  wsClient.start()
})

onUnmounted(() => {
  if (statusTimer != null) clearTimeout(statusTimer)
  if (noticeTimer != null) clearTimeout(noticeTimer)
  wsClient?.stop()
})
</script>
