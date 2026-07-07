<template>
  <dialog ref="dlg" class="settings-dialog" @cancel.prevent="close">
    <form method="dialog" class="settings-form" @submit.prevent>
      <div class="settings-form-scroll ui-scroll">
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
      <label class="idle-timeout-field">
        空闲卸载模型（分钟）
        <input
          type="number"
          min="1"
          max="1440"
          :value="settings.model_idle_timeout_minutes"
          @change="updateIdle"
        />
      </label>
      <p class="storage-hint model-lifecycle-hint">
        上次加载模型的时间：{{ formatModelTime(modelLifecycle.last_loaded_at) }}
      </p>
      <p class="storage-hint model-lifecycle-hint">
        上次卸载模型的时间：{{ formatModelTime(modelLifecycle.last_unloaded_at) }}
      </p>
      <p class="storage-hint model-lifecycle-hint">
        当前显存占用：{{ formatGpuMemory(modelLifecycle) }}
      </p>
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
      </div>
      <div class="settings-form-footer">
        <button type="button" class="ghost" @click="close">关闭</button>
      </div>
    </form>
    <LogViewerDialog ref="logViewerRef" />
  </dialog>
</template>

<script setup>
import { ref } from 'vue'
import { api } from '../api.js'
import { useModalAnimation } from '../composables/useModalAnimation.js'
import LogViewerDialog from './LogViewerDialog.vue'

const props = defineProps({
  settings: { type: Object, required: true },
  secrets: { type: Object, required: true },
})

const emit = defineEmits(['refresh'])

const dlg = ref(null)
const logViewerRef = ref(null)
const { openModal, closeModal } = useModalAnimation()
const storageStats = ref({ count: 0, bytes: 0 })
const modelLifecycle = ref({ last_loaded_at: null, last_unloaded_at: null })
const clearing = ref(false)
const clearMessage = ref('')

function formatSize(bytes) {
  if (!bytes) return '0 B'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function formatModelTime(iso) {
  if (!iso) return '暂无记录'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '暂无记录'
  const month = d.getMonth() + 1
  const day = d.getDate()
  const hour = String(d.getHours()).padStart(2, '0')
  const minute = String(d.getMinutes()).padStart(2, '0')
  return `${month}月${day}日 ${hour}:${minute}`
}

function formatGpuMemory(status) {
  if (!status?.gpu_available) return '不适用（CPU 模式）'
  const allocated = status.gpu_memory_allocated_bytes ?? 0
  const total = status.gpu_memory_total_bytes
  if (total) return `${formatSize(allocated)} / ${formatSize(total)}`
  return formatSize(allocated)
}

async function loadModelLifecycle() {
  try {
    const s = await api.status()
    modelLifecycle.value = {
      last_loaded_at: s.model_last_loaded_at,
      last_unloaded_at: s.model_last_unloaded_at,
      gpu_available: s.gpu_available,
      gpu_memory_allocated_bytes: s.gpu_memory_allocated_bytes,
      gpu_memory_reserved_bytes: s.gpu_memory_reserved_bytes,
      gpu_memory_total_bytes: s.gpu_memory_total_bytes,
      gpu_device: s.gpu_device,
    }
  } catch {
    modelLifecycle.value = {
      last_loaded_at: null,
      last_unloaded_at: null,
      gpu_available: false,
      gpu_memory_allocated_bytes: null,
      gpu_memory_reserved_bytes: null,
      gpu_memory_total_bytes: null,
      gpu_device: null,
    }
  }
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
  openModal(dlg.value)
  loadStorageStats()
  loadModelLifecycle()
}

async function close() {
  await closeModal(dlg.value)
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
