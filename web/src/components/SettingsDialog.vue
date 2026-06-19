<template>
  <dialog ref="dlg" class="settings-dialog">
    <form method="dialog" class="settings-form" @submit.prevent>
      <h2>设置</h2>
      <label class="toggle">
        <input type="checkbox" :checked="settings.clipboard_enabled" @change="toggleClipboard" />
        剪贴板监听
      </label>
      <label class="toggle">
        <input type="checkbox" :checked="settings.auto_open_feishu" @change="toggleAutoOpenFeishu" />
        完成后自动打开飞书链接
      </label>
      <label>
        润色模型
        <select :value="settings.deepseek_model" @change="updateDeepseekModel">
          <option value="deepseek-v4-pro">DeepSeek V4 Pro</option>
          <option value="deepseek-v4-flash">DeepSeek V4 Flash</option>
        </select>
      </label>
      <label>
        空闲卸载模型（分钟）
        <input
          type="number"
          min="1"
          max="1440"
          :value="settings.model_idle_timeout_minutes"
          @change="updateIdle"
        />
      </label>
      <fieldset class="storage-section">
        <legend>本地整理稿</legend>
        <div>共 {{ storageStats.count }} 篇，约 {{ formatSize(storageStats.bytes) }}</div>
        <p class="storage-hint">清除后追问将不可用，需重新处理视频后才会再次生成。</p>
        <button
          type="button"
          class="danger"
          :disabled="clearing || storageStats.count === 0"
          @click="clearPolished"
        >
          {{ clearing ? '清除中…' : '清除本地整理稿' }}
        </button>
        <p v-if="clearMessage" class="storage-message">{{ clearMessage }}</p>
      </fieldset>
      <fieldset class="logs-section">
        <legend>运行日志</legend>
        <p class="logs-hint">服务运行日志保存在项目 logs/ 目录。</p>
        <button type="button" @click="openLogs">查看日志</button>
      </fieldset>
      <fieldset class="secrets">
        <legend>密钥配置（只读，请编辑 .env）</legend>
        <div>DeepSeek：{{ secrets.deepseek_configured ? '已配置' : '未配置' }}</div>
        <div>飞书：{{ secrets.feishu_configured ? '已配置' : '未配置' }}</div>
      </fieldset>
      <button type="button" @click="close">关闭</button>
    </form>
    <LogViewerDialog ref="logViewerRef" />
  </dialog>
</template>

<script setup>
import { ref } from 'vue'
import { api } from '../api.js'
import LogViewerDialog from './LogViewerDialog.vue'

const props = defineProps({
  settings: { type: Object, required: true },
  secrets: { type: Object, required: true },
})

const emit = defineEmits(['refresh'])

const dlg = ref(null)
const logViewerRef = ref(null)
const storageStats = ref({ count: 0, bytes: 0 })
const clearing = ref(false)
const clearMessage = ref('')

function formatSize(bytes) {
  if (!bytes) return '0 B'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

async function loadStorageStats() {
  try {
    storageStats.value = await api.polishedStorage()
  } catch {
    storageStats.value = { count: 0, bytes: 0 }
  }
}

function open() {
  clearMessage.value = ''
  dlg.value?.showModal()
  loadStorageStats()
}

function close() {
  dlg.value?.close()
}

function openLogs() {
  logViewerRef.value?.open()
}

async function toggleClipboard(ev) {
  await api.updateSettings({ clipboard_enabled: ev.target.checked })
  emit('refresh')
}

async function toggleAutoOpenFeishu(ev) {
  await api.updateSettings({ auto_open_feishu: ev.target.checked })
  emit('refresh')
}

async function updateDeepseekModel(ev) {
  await api.updateSettings({ deepseek_model: ev.target.value })
  emit('refresh')
}

async function updateIdle(ev) {
  const v = parseInt(ev.target.value, 10)
  if (v >= 1) {
    await api.updateSettings({ model_idle_timeout_minutes: v })
    emit('refresh')
  }
}

async function clearPolished() {
  if (clearing.value || storageStats.value.count === 0) return
  if (!window.confirm(`确定清除 ${storageStats.value.count} 篇本地整理稿吗？`)) return

  clearing.value = true
  clearMessage.value = ''
  try {
    const result = await api.clearPolishedStorage()
    clearMessage.value = `已清除 ${result.deleted_count} 篇，释放约 ${formatSize(result.freed_bytes)}`
    await loadStorageStats()
  } catch (e) {
    clearMessage.value = e.message || '清除失败'
  } finally {
    clearing.value = false
  }
}

defineExpose({ open })
</script>
