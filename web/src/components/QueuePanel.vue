<template>
  <div class="queue-panel card">
    <h2>队列</h2>
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
  taskFailReason,
} from '../composables.js'
import TaskLabel from './TaskLabel.vue'

defineProps({
  items: { type: Array, default: () => [] },
})

const emit = defineEmits(['delete', 'retry', 'reorder'])
const dragFrom = ref(null)

function failReason(item) {
  return taskFailReason(item)
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
