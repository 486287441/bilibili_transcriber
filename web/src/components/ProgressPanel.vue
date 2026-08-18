<template>
  <div class="progress-panel card">
    <h2>当前任务</h2>
    <div v-if="!active" class="empty">暂无进行中的任务</div>
    <template v-else>
      <TaskLabel class="progress-title" :url="active.url" :title="active.title" link />
      <div class="meta">
        <span v-if="active.duration_sec">时长 {{ formatDuration(active.duration_sec) }}</span>
        <span class="route-badge" :data-route="routeKind">{{ routeLabel }}</span>
        <span class="phase-tag">{{ phaseLabel }}</span>
      </div>
      <div class="phase-bars">
        <div
          v-for="item in phaseBars"
          :key="item.key"
          class="phase-bar-row"
          :class="rowClass(item.key)"
        >
          <div class="phase-bar-head">
            <span class="phase-bar-label">{{ item.label }}</span>
            <span class="phase-bar-pct">{{ item.display.toFixed(1) }}%</span>
          </div>
          <div class="bar-wrap">
            <div class="bar" :style="{ width: item.display + '%' }" />
          </div>
        </div>
      </div>
      <div class="bar-footer">
        <span>{{ phaseLabel }}</span>
        <span>{{ etaText }}</span>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed, toRef } from 'vue'
import {
  PHASE_LABELS,
  formatEta,
  transcriptionPhaseLabel,
  transcriptionRouteLabel,
  useSmoothEta,
  useSmoothPhaseProgress,
} from '../composables.js'
import TaskLabel from './TaskLabel.vue'

const props = defineProps({
  active: { type: Object, default: null },
  progress: { type: Object, default: null },
})

const phases = ['download', 'transcribe', 'polish']
const progressRef = toRef(props, 'progress')
const { download, transcribe, polish } = useSmoothPhaseProgress(progressRef)
const { displayEta } = useSmoothEta(progressRef)

const routeState = computed(() => {
  const progressHasRoute = props.progress && (
    Object.prototype.hasOwnProperty.call(props.progress, 'requested_route') ||
    Object.prototype.hasOwnProperty.call(props.progress, 'resolved_route')
  )
  const activeHasRoute = props.active && (
    Object.prototype.hasOwnProperty.call(props.active, 'requested_route') ||
    Object.prototype.hasOwnProperty.call(props.active, 'resolved_route')
  )
  if (!progressHasRoute && !activeHasRoute) return props.active || props.progress || {}
  return {
    requested_route: props.progress?.requested_route ?? props.active?.requested_route,
    resolved_route: props.progress?.resolved_route ?? props.active?.resolved_route,
  }
})
const routeKind = computed(() => (
  routeState.value.resolved_route || routeState.value.requested_route || 'asr'
))
const routeLabel = computed(() => transcriptionRouteLabel(routeState.value))
const transcribeLabel = computed(() => transcriptionPhaseLabel(routeState.value))

const phaseBars = computed(() => [
  { key: 'download', label: PHASE_LABELS.download, display: download.value },
  { key: 'transcribe', label: transcribeLabel.value, display: transcribe.value },
  { key: 'polish', label: PHASE_LABELS.polish, display: polish.value },
])

const phaseLabel = computed(() => {
  if (props.progress?.phase === 'transcribe') return transcribeLabel.value
  return PHASE_LABELS[props.progress?.phase] || '准备中'
})
const etaText = computed(() =>
  formatEta(displayEta.value, props.progress?.phase),
)

function rowClass(p) {
  const order = phases.indexOf(props.progress?.phase)
  const idx = phases.indexOf(p)
  if (order < 0) return {}
  if (idx < order) return { done: true }
  if (idx === order) return { active: true }
  return { pending: true }
}

function formatDuration(sec) {
  const m = Math.floor(sec / 60)
  const s = Math.round(sec % 60)
  return `${m}:${String(s).padStart(2, '0')}`
}
</script>
