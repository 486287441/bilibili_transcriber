<template>
  <div class="queue-panel card">
    <h2>队列</h2>
    <form class="add-form" @submit.prevent="submit">
      <input v-model="urlInput" placeholder="本程序后台自动监听剪贴板" />
      <select v-model="requestedRoute" class="route-select" aria-label="转写路线" title="选择转写路线">
        <option v-for="option in TRANSCRIPTION_ROUTE_OPTIONS" :key="option.value" :value="option.value">
          {{ option.label }}
        </option>
      </select>
      <button type="submit" :disabled="adding">添加</button>
    </form>
    <p v-if="error" class="error">{{ error }}</p>
    <ul class="queue-list">
      <li
        v-for="(item, idx) in items"
        :key="item.id"
        draggable="true"
        @dragstart="onDragStart(idx)"
        @dragover.prevent
        @drop="onDrop(idx)"
      >
        <div class="row-main">
          <span class="pos">#{{ item.position }}</span>
          <div class="info">
            <TaskLabel :url="item.url" :title="item.title" link />
            <div class="task-badges">
              <span class="badge" :data-status="item.status">{{ STATUS_LABELS[item.status] || item.status }}</span>
              <span
                class="route-badge"
                :data-route="item.resolved_route || item.requested_route || 'asr'"
              >{{ transcriptionRouteLabel(item) }}</span>
            </div>
            <span
              v-if="item.status === 'failed' && failReason(item)"
              class="fail-reason"
              :title="item.error_message"
            >{{ failReason(item) }}</span>
          </div>
        </div>
        <div class="actions">
          <button v-if="item.status === 'failed'" type="button" @click="$emit('retry', item.id)">重试</button>
          <button type="button" class="danger" @click="$emit('delete', item.id)">删除</button>
        </div>
      </li>
    </ul>
    <p v-if="!items.length" class="empty">队列为空</p>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import {
  STATUS_LABELS,
  TRANSCRIPTION_ROUTE_OPTIONS,
  taskFailReason,
  transcriptionRouteLabel,
} from '../composables.js'
import TaskLabel from './TaskLabel.vue'

defineProps({
  items: { type: Array, default: () => [] },
})

const emit = defineEmits(['add', 'delete', 'retry', 'reorder'])

const urlInput = ref('')
const requestedRoute = ref('auto')
const adding = ref(false)
const error = ref('')
const dragFrom = ref(null)

function failReason(item) {
  return taskFailReason(item)
}

function submit() {
  error.value = ''
  const url = urlInput.value.trim()
  if (!url) return
  adding.value = true

  let settled = false
  const finish = () => {
    if (settled) return false
    settled = true
    adding.value = false
    return true
  }

  try {
    emit('add', {
      url,
      requestedRoute: requestedRoute.value,
      onSuccess: () => {
        if (!finish()) return
        urlInput.value = ''
        requestedRoute.value = 'auto'
      },
      onError: (message) => {
        if (!finish()) return
        error.value = message || '添加失败'
      },
    })
  } catch (e) {
    if (finish()) error.value = e.message || '添加失败'
  }
}

function onDragStart(idx) {
  dragFrom.value = idx
}

function onDrop(toIdx) {
  if (dragFrom.value == null || dragFrom.value === toIdx) return
  emit('reorder', dragFrom.value, toIdx)
  dragFrom.value = null
}
</script>
