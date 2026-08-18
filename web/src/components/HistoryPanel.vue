<template>
  <div class="history-panel card">
    <div class="head" @click="toggle">
      <h2>历史记录</h2>
      <span>{{ collapsed ? '展开 ▼' : '收起 ▲' }}</span>
    </div>
    <div v-show="!collapsed">
      <div class="toolbar">
        <input v-model="query" placeholder="搜索标题或 URL…" @keyup.enter="search" />
        <button type="button" @click="search">搜索</button>
      </div>
      <div v-if="items.length" class="history-table-scroll">
        <table class="history-table">
        <colgroup>
          <col class="col-title" />
          <col class="col-site" />
          <col class="col-time" />
          <col class="col-status" />
          <col class="col-actions" />
        </colgroup>
        <thead>
          <tr>
            <th>标题</th>
            <th>来源</th>
            <th>时间</th>
            <th>状态</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in items" :key="item.id">
            <td>
              <a v-if="item.url" :href="item.url" target="_blank" rel="noopener noreferrer">
                <TaskLabel :url="item.url" :title="item.title" />
              </a>
              <TaskLabel v-else :url="item.url" :title="item.title" />
            </td>
            <td>
              <span class="tag site-tag">{{ siteLabelFor(item) }}</span>
            </td>
            <td>{{ formatTime(item.processed_at) }}</td>
            <td>
              <span class="status-cell">
                <span>{{ STATUS_LABELS[item.status] || item.status }}</span>
                <span
                  v-if="item.status === 'failed' && failReason(item)"
                  class="fail-reason"
                  :title="item.error_message"
                >{{ failReason(item) }}</span>
                <span
                  class="route-badge history-route-badge"
                  :data-route="item.resolved_route || item.requested_route || 'asr'"
                >{{ transcriptionRouteLabel(item) }}</span>
              </span>
            </td>
            <td>
              <div class="actions">
                <button
                  v-if="item.status === 'completed' && !item.recommendation"
                  type="button"
                  class="recommendation-pill"
                  data-grade="pending"
                  :title="recommendationTitle(item)"
                  :disabled="evaluatingIds.has(item.id)"
                  @click="$emit('evaluate-recommendation', item.id)"
                >{{ recommendationLabel(item) }}</button>
                <button
                  v-else-if="item.status === 'completed'"
                  type="button"
                  class="recommendation-pill"
                  :data-grade="item.recommendation.grade"
                  :title="recommendationTitle(item)"
                  @click="openRecommendation(item)"
                >{{ recommendationLabel(item) }}</button>
                <button
                  v-if="item.status === 'completed'"
                  type="button"
                  @click="openFollowUp(item)"
                >追问</button>
                <button
                  v-if="item.output_doc_url"
                  type="button"
                  @click="openDoc(item.output_doc_url)"
                >详情</button>
                <div v-if="item.status === 'completed'" class="reprocess-control">
                  <select
                    v-model="routeSelections[item.id]"
                    :aria-label="`为${item.title || '该视频'}选择重跑路线`"
                    :disabled="reprocessingIds.has(item.id)"
                  >
                    <option :value="undefined" disabled>换路线…</option>
                    <option
                      v-for="option in reprocessRouteOptions"
                      :key="option.value"
                      :value="option.value"
                      :disabled="isCurrentRoute(item, option.value)"
                    >
                      {{ option.label }}{{ isCurrentRoute(item, option.value) ? '（当前）' : '' }}
                    </option>
                  </select>
                  <button
                    type="button"
                    class="ghost reprocess-button"
                    :disabled="!routeSelections[item.id] || reprocessingIds.has(item.id)"
                    @click="requestReprocess(item)"
                  >{{ reprocessingIds.has(item.id) ? '加入中…' : '重跑' }}</button>
                </div>
                <button type="button" class="danger" @click="$emit('delete', item.id)">删除</button>
              </div>
            </td>
          </tr>
        </tbody>
        </table>
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
  <RecommendationDialog ref="recommendationRef" />
</template>

<script setup>
import { computed, ref } from 'vue'
import {
  STATUS_LABELS,
  TRANSCRIPTION_ROUTE_OPTIONS,
  effectiveTranscriptionRoute,
  siteLabelFor,
  taskFailReason,
  transcriptionRouteLabel,
} from '../composables.js'
import TaskLabel from './TaskLabel.vue'
import FollowUpDialog from './FollowUpDialog.vue'
import RecommendationDialog from './RecommendationDialog.vue'

const props = defineProps({
  items: { type: Array, default: () => [] },
  total: { type: Number, default: 0 },
  page: { type: Number, default: 1 },
  pageSize: { type: Number, default: 20 },
  collapsed: { type: Boolean, default: false },
  evaluatingIds: { type: Set, default: () => new Set() },
  reprocessingIds: { type: Set, default: () => new Set() },
})

const emit = defineEmits([
  'search',
  'page',
  'delete',
  'evaluate-recommendation',
  'reprocess-route',
  'toggle-collapse',
])

const query = ref('')
const followUpRef = ref(null)
const recommendationRef = ref(null)
const routeSelections = ref({})
const reprocessRouteOptions = TRANSCRIPTION_ROUTE_OPTIONS.filter((option) => option.value !== 'auto')

function failReason(item) {
  return taskFailReason(item)
}

function recommendationLabel(item) {
  const recommendation = item?.recommendation
  if (!recommendation) return props.evaluatingIds.has(item.id) ? '正在评估…' : '推荐未评估'
  if (recommendation.is_dual_score) {
    return `${recommendation.verdict || verdictFor(recommendation)} · ${recommendation.grade}级 · 内容${Math.round(recommendation.content_score)} / 原片${Math.round(recommendation.incremental_score)}`
  }
  return `${recommendation.verdict || verdictFor(recommendation)} · ${recommendation.grade}级 · ${Math.round(recommendation.score)}分`
}

function verdictFor(recommendation) {
  if (['S', 'A'].includes(recommendation?.grade)) return '推荐观看'
  if (recommendation?.grade === 'B') return '值得了解'
  return '可略过'
}

function recommendationTitle(item) {
  const recommendation = item?.recommendation
  if (!recommendation) return '点击后立即使用 DeepSeek 评估'
  return '点击查看详细评分理由'
}

function openRecommendation(item) {
  recommendationRef.value?.open(item)
}

const totalPages = computed(() => Math.max(1, Math.ceil(props.total / props.pageSize)))

function openDoc(url) {
  window.open(url, '_blank', 'noopener,noreferrer')
}

function openFollowUp(item) {
  followUpRef.value?.open(item)
}

function isCurrentRoute(item, route) {
  return effectiveTranscriptionRoute(item) === route
}

function requestReprocess(item) {
  const requestedRoute = routeSelections.value[item.id]
  if (!requestedRoute || props.reprocessingIds.has(item.id)) return
  emit('reprocess-route', {
    id: item.id,
    requestedRoute,
    onSuccess: () => {
      delete routeSelections.value[item.id]
    },
  })
}

function search() {
  emit('search', query.value.trim())
}

function toggle() {
  emit('toggle-collapse')
}

function formatTime(iso) {
  if (!iso) return '-'
  return new Date(iso).toLocaleString('zh-CN')
}
</script>
