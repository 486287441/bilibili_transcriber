<template>
  <dialog
    ref="dlg"
    class="task-timing-dialog"
    aria-labelledby="task-timing-title"
    @close="onClose"
    @cancel.prevent="close"
  >
    <section class="task-timing-shell">
      <header class="task-timing-header">
        <div>
          <span>PROCESSING SUMMARY</span>
          <h2 id="task-timing-title">任务耗时明细</h2>
          <p v-if="title">{{ title }}</p>
        </div>
        <button ref="closeButton" type="button" class="ghost" @click="close">关闭</button>
      </header>

      <div class="task-timing-content">
        <section class="task-timing-overview" aria-label="总耗时概览">
          <div>
            <span>全流程总耗时</span>
            <strong>{{ formatDuration(timing.total_seconds) }}</strong>
          </div>
          <p v-if="slowestPhase">
            最慢阶段为<strong>{{ slowestPhase.label }}</strong>，占总耗时约 {{ phasePercent(slowestPhase) }}%。
          </p>
        </section>

        <section class="task-timing-phases" aria-label="各阶段耗时">
          <div class="task-timing-section-title">
            <strong>阶段明细</strong>
            <span>共 {{ phases.length }} 个阶段</span>
          </div>
          <ol>
            <li v-for="phase in phases" :key="phase.key" :class="{ slowest: phase.key === timing.slowest_key }">
              <div class="task-timing-phase-heading">
                <span>{{ phase.label }}</span>
                <strong>{{ formatSeconds(phase.seconds) }}</strong>
              </div>
              <div class="task-timing-track" aria-hidden="true">
                <span :style="{ width: `${Math.max(2, phasePercent(phase))}%` }" />
              </div>
              <small>{{ phasePercent(phase) }}%</small>
            </li>
          </ol>
        </section>
      </div>
    </section>
  </dialog>
</template>

<script setup>
import { computed, nextTick, ref } from 'vue'
import { useBackdropDismiss, useModalAnimation } from '../composables/useModalAnimation.js'

const dlg = ref(null)
const closeButton = ref(null)
const title = ref('')
const timing = ref({ total_seconds: 0, phases: [] })
const { openModal, closeModal } = useModalAnimation()
const phases = computed(() => Array.isArray(timing.value.phases) ? timing.value.phases : [])
const slowestPhase = computed(() => (
  phases.value.find((phase) => phase.key === timing.value.slowest_key)
  || phases.value.reduce((best, phase) => !best || phase.seconds > best.seconds ? phase : best, null)
))

function phasePercent(phase) {
  const total = Number(timing.value.total_seconds) || 0
  return total > 0 ? Math.round((Number(phase.seconds) || 0) / total * 100) : 0
}

function formatSeconds(value) {
  const seconds = Math.max(0, Number(value) || 0)
  if (seconds > 0 && seconds < 0.1) return '< 0.1 秒'
  if (seconds < 10) return `${seconds.toFixed(2).replace(/0+$/, '').replace(/\.$/, '')} 秒`
  return `${seconds.toFixed(1).replace(/\.0$/, '')} 秒`
}

function formatDuration(value) {
  const seconds = Math.max(0, Number(value) || 0)
  if (seconds < 60) return formatSeconds(seconds)
  const minutes = Math.floor(seconds / 60)
  const remainder = Math.round(seconds % 60)
  return `${minutes} 分 ${remainder} 秒`
}

async function close() {
  unbindBackdropDismiss()
  await closeModal(dlg.value)
}

const { bind: bindBackdropDismiss, unbind: unbindBackdropDismiss } = useBackdropDismiss(dlg, close)

async function open(item) {
  title.value = item.title || '未命名任务'
  timing.value = item.timing || { total_seconds: 0, phases: [] }
  openModal(dlg.value)
  bindBackdropDismiss()
  await nextTick()
  closeButton.value?.focus({ preventScroll: true })
}

function onClose() {
  unbindBackdropDismiss()
}

defineExpose({ open })
</script>
