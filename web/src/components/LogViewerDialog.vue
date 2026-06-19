<template>
  <dialog ref="dlg" class="log-viewer-dialog" @close="onClose">
    <div class="log-viewer-shell">
      <header class="log-viewer-head">
        <h2>运行日志</h2>
        <div class="log-viewer-actions">
          <label class="log-lines-label">
            行数
            <select v-model.number="lineCount" @change="loadContent">
              <option :value="200">200</option>
              <option :value="500">500</option>
              <option :value="1000">1000</option>
              <option :value="2000">2000</option>
            </select>
          </label>
          <button type="button" class="ghost" :disabled="loading" @click="loadContent">
            {{ loading ? '刷新中…' : '刷新' }}
          </button>
          <button type="button" class="ghost" @click="close">关闭</button>
        </div>
      </header>

      <div class="log-viewer-toolbar">
        <label>
          文件
          <select v-model="selectedFile" :disabled="!files.length" @change="loadContent">
            <option v-for="f in files" :key="f.name" :value="f.name">
              {{ f.name }} ({{ formatSize(f.size) }})
            </option>
          </select>
        </label>
        <span v-if="meta" class="log-meta">
          {{ meta.truncated ? `仅显示最后 ${meta.lines_requested} 行 · ` : '' }}
          共 {{ formatSize(meta.size) }}
        </span>
      </div>

      <p v-if="error" class="log-error">{{ error }}</p>
      <p v-else-if="!files.length && !loading" class="log-empty">暂无日志文件（logs/ 目录为空）</p>
      <pre v-else ref="preRef" class="log-content">{{ content }}</pre>
    </div>
  </dialog>
</template>

<script setup>
import { nextTick, ref } from 'vue'
import { api } from '../api.js'

const dlg = ref(null)
const preRef = ref(null)
const files = ref([])
const selectedFile = ref('')
const lineCount = ref(500)
const content = ref('')
const meta = ref(null)
const loading = ref(false)
const error = ref('')

function formatSize(bytes) {
  if (!bytes) return '0 B'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

async function loadFileList() {
  const data = await api.logs()
  files.value = data.files || []
  if (!files.value.length) {
    selectedFile.value = ''
    return
  }
  if (!selectedFile.value || !files.value.some((f) => f.name === selectedFile.value)) {
    selectedFile.value = files.value[0].name
  }
}

async function loadContent() {
  if (!selectedFile.value) {
    content.value = ''
    meta.value = null
    return
  }
  loading.value = true
  error.value = ''
  try {
    const data = await api.logContent(selectedFile.value, lineCount.value)
    content.value = data.content || ''
    meta.value = data
    await nextTick()
    if (preRef.value) {
      preRef.value.scrollTop = preRef.value.scrollHeight
    }
  } catch (e) {
    error.value = e.message || '加载日志失败'
    content.value = ''
    meta.value = null
  } finally {
    loading.value = false
  }
}

async function open() {
  error.value = ''
  content.value = ''
  meta.value = null
  dlg.value?.showModal()
  loading.value = true
  try {
    await loadFileList()
    await loadContent()
  } catch (e) {
    error.value = e.message || '加载日志列表失败'
  } finally {
    loading.value = false
  }
}

function close() {
  dlg.value?.close()
}

function onClose() {
  error.value = ''
}

defineExpose({ open })
</script>
