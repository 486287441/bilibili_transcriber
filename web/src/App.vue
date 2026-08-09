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
        <span v-if="wsConnected" class="tag" :class="'tag-' + modelStatus.variant" :title="modelStatus.title">
          {{ modelStatus.text }}
        </span>
        <div
          v-if="wsConnected && modelLoadVisible"
          class="model-load-bar"
          title="模型加载进度"
        >
          <div class="model-load-bar-fill" :style="{ width: modelLoadDisplay + '%' }" />
        </div>
      </div>
      <button type="button" class="ghost" @click="openSettings">设置</button>
    </header>

    <main class="layout">
      <QueuePanel
        :items="queueItems"
        @add="onAddQueue"
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
      :collapsed="historyCollapsed"
      :evaluating-ids="recommendationEvaluating"
      @search="onHistorySearch"
      @page="onHistoryPage"
      @delete="onDeleteHistory"
      @evaluate-recommendation="onEvaluateRecommendation"
      @toggle-collapse="toggleHistoryCollapsed"
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
import { storageGet, storageSet } from './storage.js'
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
})
const secrets = ref({})
const serviceStatus = ref({ model_loaded: false, model_loading: false })
const { display: modelLoadDisplay, visible: modelLoadVisible } = useModelLoadProgress(serviceStatus)
const currentProgress = ref(null)
const historyItems = ref([])
const historyTotal = ref(0)
const historyPage = ref(1)
const historyQuery = ref('')
const historyCollapsed = ref(storageGet('ui.historyCollapsed', false))
const settingsRef = ref(null)
const recommendationEvaluating = ref(new Set())
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

function setRecommendationEvaluating(id, evaluating) {
  const next = new Set(recommendationEvaluating.value)
  if (evaluating) next.add(id)
  else next.delete(id)
  recommendationEvaluating.value = next
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
  queueItems.value = await api.queue()
  await syncProgress()
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
    currentProgress.value = msg.payload
    return
  }
  if (msg.type === 'queue.updated' || msg.type === 'task.state_changed') {
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
  if (msg.type === 'history.created' || msg.type === 'history.deleted') {
    refreshHistory()
    return
  }
  if (msg.type === 'history.recommendation_completed') {
    setRecommendationEvaluating(msg.payload?.id, false)
    refreshHistory()
    showNotice('推荐指数评估完成')
    return
  }
  if (msg.type === 'history.recommendation_failed') {
    setRecommendationEvaluating(msg.payload?.id, false)
    showNotice(msg.payload?.error || '推荐指数评估失败')
  }
}

async function onAddQueue(url) {
  try {
    await api.addQueue(url)
    await refreshQueue()
  } catch (e) {
    alert(e.message || '添加失败')
  }
}

async function onDeleteQueue(id) {
  const backup = queueItems.value
  queueItems.value = queueItems.value.filter((t) => t.id !== id)
  if (currentProgress.value?.task_id === id) {
    currentProgress.value = null
  }
  try {
    await api.deleteQueue(id)
    await refreshQueue()
  } catch (e) {
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

async function onEvaluateRecommendation(id) {
  if (recommendationEvaluating.value.has(id)) return
  setRecommendationEvaluating(id, true)
  try {
    await api.evaluateRecommendation(id)
    showNotice('已开始评估')
  } catch (e) {
    setRecommendationEvaluating(id, false)
    showNotice(e.message || '启动评估失败')
  }
}

function toggleHistoryCollapsed() {
  historyCollapsed.value = !historyCollapsed.value
  storageSet('ui.historyCollapsed', historyCollapsed.value)
}

function openSettings() {
  settingsRef.value?.open()
}

async function loadInitialData() {
  try {
    const data = await api.bootstrap()
    queueItems.value = data.queue ?? []
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
