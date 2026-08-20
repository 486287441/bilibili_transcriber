<template>
  <div class="history-panel card">
    <div class="head">
      <h2>历史记录</h2>
    </div>
    <div>
      <div class="toolbar">
        <input v-model="query" placeholder="搜索标题…" @keyup.enter="search" />
        <button type="button" @click="search">搜索</button>
      </div>
      <div v-if="items.length" class="history-list" role="list">
        <article
          v-for="item in items"
          :key="item.id"
          class="history-entry"
          :data-status="item.status"
          :data-state="historyItemState(item)"
          role="listitem"
        >
          <div class="history-entry-main">
            <a
              v-if="item.url"
              class="history-entry-title"
              :href="item.url"
              target="_blank"
              rel="noopener noreferrer"
              :title="item.title || item.url"
            >{{ item.title || '未命名视频' }}</a>
            <span v-else class="history-entry-title">{{ item.title || '未命名视频' }}</span>
            <div class="history-entry-meta">
              <time :datetime="item.processed_at || undefined">{{ formatTime(item.processed_at) }}</time>
            </div>
          </div>

          <div class="history-entry-result">
            <div class="history-state-line">
              <span class="history-status">
                <span class="history-status-dot" aria-hidden="true"></span>
                {{ STATUS_LABELS[item.status] || item.status }}
              </span>
            </div>
            <span
              v-if="item.status === 'failed' && failReason(item)"
              class="fail-reason"
              :title="item.error_message"
            >{{ failReason(item) }}</span>
            <span
              v-if="shouldShowPublishStatus(item)"
              class="history-publish-status"
              :data-status="item.publish_status || (item.output_doc_url ? 'published' : 'pending')"
              :title="item.publish_error || ''"
            >{{ publishStatusLabel(item) }}</span>
          </div>

          <div class="history-entry-actions">
            <div class="history-primary-actions">
              <button
                v-if="item.output_doc_url"
                type="button"
                class="history-action history-action-primary"
                @click="openDoc(item.output_doc_url)"
              >查看结果</button>
              <button
                v-if="item.status === 'completed' && item.publish_status === 'failed'"
                type="button"
                class="history-action ghost"
                :disabled="publishRetryingIds.has(item.id)"
                @click="$emit('retry-publish', item.id)"
              >{{ publishRetryingIds.has(item.id) ? '重试中…' : '重试飞书' }}</button>
              <button
                v-if="item.status === 'completed'"
                type="button"
                class="history-action ghost"
                @click="openFollowUp(item)"
              >追问</button>
              <button
                type="button"
                class="history-action history-delete"
                @click="$emit('delete', item.id)"
              >删除</button>
            </div>
          </div>
        </article>
      </div>
      <p v-else class="empty">暂无历史</p>
      <div v-if="total > pageSize" class="pager">
        <button :disabled="page <= 1" @click="$emit('page', page - 1)">上一页</button>
        <span>{{ page }} / {{ totalPages }}</span>
        <button :disabled="page >= totalPages" @click="$emit('page', page + 1)">下一页</button>
      </div>
    </div>
  </div>
  <FollowUpDialog ref="followUpRef" />
</template>

<script setup>
import { computed, ref } from 'vue'
import {
  STATUS_LABELS,
  taskFailReason,
} from '../composables.js'
import FollowUpDialog from './FollowUpDialog.vue'

const props = defineProps({
  items: { type: Array, default: () => [] },
  total: { type: Number, default: 0 },
  page: { type: Number, default: 1 },
  pageSize: { type: Number, default: 20 },
  publishRetryingIds: { type: Set, default: () => new Set() },
})

const emit = defineEmits([
  'search',
  'page',
  'delete',
  'retry-publish',
])

const query = ref('')
const followUpRef = ref(null)

function failReason(item) {
  return taskFailReason(item)
}

function publishStatusLabel(item) {
  const status = item.publish_status || (item.output_doc_url ? 'published' : 'pending')
  return {
    pending: '飞书待发布',
    publishing: '飞书发布中…',
    published: '飞书已发布',
    failed: '飞书发布失败',
    not_requested: '仅本地稿',
  }[status] || '飞书待发布'
}

function shouldShowPublishStatus(item) {
  if (item.status !== 'completed') return false
  const status = item.publish_status || (item.output_doc_url ? 'published' : 'pending')
  return status === 'pending' || status === 'publishing' || status === 'failed'
}

function historyItemState(item) {
  if (item.status === 'failed') return 'error'
  if (item.status === 'completed') return 'success'
  return 'default'
}

const totalPages = computed(() => Math.max(1, Math.ceil(props.total / props.pageSize)))

function openDoc(url) {
  window.open(url, '_blank', 'noopener,noreferrer')
}

function openFollowUp(item) {
  followUpRef.value?.open(item)
}

function search() {
  emit('search', query.value.trim())
}

function formatTime(iso) {
  if (!iso) return '-'
  return new Date(iso).toLocaleString('zh-CN')
}
</script>
