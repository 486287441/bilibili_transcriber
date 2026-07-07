<template>
  <dialog ref="dlg" class="followup-dialog" @close="onClose" @cancel.prevent="close">
    <div class="followup-shell">
      <header class="followup-head">
        <div>
          <h2>追问</h2>
          <p v-if="title" class="followup-subtitle">{{ title }}</p>
        </div>
        <div class="followup-head-actions">
          <button
            type="button"
            class="ghost followup-claude-btn"
            :disabled="!!loadError || !followupContext || copying"
            @click="copyForClaude"
          >
            {{ copyLabel }}
          </button>
          <button type="button" class="ghost" @click="close">关闭</button>
        </div>
      </header>

      <div ref="scrollRef" class="followup-messages">
        <p v-if="loadError" class="error">{{ loadError }}</p>
        <p v-else-if="!messages.length && !pending" class="empty-hint">
          基于整理后文稿向 AI 提问，例如：「这篇文章讲了什么？」
        </p>

        <template v-for="(msg, i) in messages" :key="i">
          <div
            class="chat-bubble"
            :class="[msg.role, { 'animate-in': msg.animateIn }]"
            @animationend="msg.animateIn = false"
          >
            <div class="chat-role">{{ msg.role === 'user' ? '你' : 'AI' }}</div>
            <div v-if="msg.role === 'assistant' && msg.thinking" class="thinking-block">
              <button
                type="button"
                class="thinking-toggle"
                @click="msg.thinkingCollapsed = !msg.thinkingCollapsed"
              >
                思考过程 {{ msg.thinkingCollapsed ? '▸' : '▾' }}
              </button>
              <transition name="thinking-collapse">
                <div v-if="!msg.thinkingCollapsed" class="thinking-panel">
                  <MarkdownContent :content="msg.thinking" dark />
                </div>
              </transition>
            </div>
            <div class="chat-text" :class="{ 'chat-text-md': msg.role === 'assistant' }">
              <MarkdownContent v-if="msg.role === 'assistant'" :content="msg.content" />
              <template v-else>{{ msg.content }}</template>
            </div>
          </div>
        </template>

        <div v-if="pending" class="chat-bubble assistant pending">
          <div class="chat-role">AI</div>
          <div class="pending-indicator">
            <span class="thinking-dots" aria-hidden="true">
              <span /><span /><span />
            </span>
          </div>
          <div v-if="pending.thinking" class="thinking-panel thinking-panel-live">
            <MarkdownContent :content="pending.thinking" dark />
          </div>
        </div>
      </div>

      <form class="followup-compose" @submit.prevent="send">
        <p v-if="sendError" class="error compose-error">{{ sendError }}</p>
        <div class="followup-compose-row">
          <textarea
            ref="inputRef"
            v-model="draft"
            rows="2"
            placeholder="输入你的问题…"
            :disabled="loading || !!loadError || !historyId"
            @keydown.enter.exact.prevent="send"
          />
          <button type="submit" :disabled="loading || !draft.trim() || !!loadError || !historyId">
            发送
          </button>
        </div>
      </form>
    </div>
  </dialog>
</template>

<script setup>
import { computed, nextTick, ref } from 'vue'
import { api } from '../api.js'
import { useBackdropDismiss, useModalAnimation } from '../composables/useModalAnimation.js'
import MarkdownContent from './MarkdownContent.vue'

const CLAUDE_URL = 'https://claude.ai/new'
const CLAUDE_PROMPT_SUFFIX = '\n\n严肃客观分析这篇文章'

function buildClaudeClipboardText(articleContext) {
  return `${articleContext.trim()}${CLAUDE_PROMPT_SUFFIX}`
}

const dlg = ref(null)
const scrollRef = ref(null)
const inputRef = ref(null)
const { openModal, closeModal } = useModalAnimation()

let closing = false

async function close() {
  if (closing) return
  closing = true
  try {
    await closeModal(dlg.value)
  } finally {
    closing = false
  }
}

const { bind: bindBackdropDismiss, unbind: unbindBackdropDismiss } = useBackdropDismiss(dlg, close)
const historyId = ref(null)
const title = ref('')
const followupContext = ref('')
const messages = ref([])
const pending = ref(null)
const draft = ref('')
const loading = ref(false)
const loadError = ref('')
const sendError = ref('')
const copying = ref(false)
const copyDone = ref(false)

const copyLabel = computed(() => {
  if (copying.value) return '复制中…'
  if (copyDone.value) return '已复制'
  return '复制去问claude'
})

function toApiMessages(msgs) {
  return msgs
    .filter((m) => m.role === 'user' || m.role === 'assistant')
    .map(({ role, content }) => ({ role, content }))
}

async function scrollToBottom() {
  await nextTick()
  scrollRef.value?.scrollTo({ top: scrollRef.value.scrollHeight, behavior: 'smooth' })
}

async function focusInput() {
  await nextTick()
  const el = inputRef.value
  if (el && !el.disabled) {
    el.focus({ preventScroll: true })
  }
}

async function open(item) {
  historyId.value = item.id
  title.value = item.title || item.url
  followupContext.value = ''
  messages.value = []
  pending.value = null
  draft.value = ''
  loadError.value = ''
  sendError.value = ''
  loading.value = false
  copyDone.value = false
  openModal(dlg.value)
  bindBackdropDismiss()
  await focusInput()

  try {
    const detail = await api.historyDetail(item.id)
    if (!detail.followup_context?.trim()) {
      loadError.value = '整理后文稿不可用，无法追问'
    } else {
      followupContext.value = detail.followup_context
    }
  } catch (e) {
    loadError.value = e.message || '加载失败'
  } finally {
    await focusInput()
  }
}

function onClose() {
  unbindBackdropDismiss()
  historyId.value = null
  followupContext.value = ''
  messages.value = []
  pending.value = null
  draft.value = ''
  loadError.value = ''
  sendError.value = ''
  loading.value = false
  copying.value = false
  copyDone.value = false
}

async function writeClipboard(text) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text)
    return
  }
  const area = document.createElement('textarea')
  area.value = text
  area.setAttribute('readonly', '')
  area.style.position = 'fixed'
  area.style.left = '-9999px'
  document.body.appendChild(area)
  area.select()
  const ok = document.execCommand('copy')
  document.body.removeChild(area)
  if (!ok) throw new Error('无法写入剪贴板')
}

async function copyForClaude() {
  const text = followupContext.value?.trim()
  if (!text || copying.value) return

  copying.value = true
  copyDone.value = false
  try {
    await writeClipboard(buildClaudeClipboardText(text))
    copyDone.value = true
    window.open(CLAUDE_URL, '_blank', 'noopener,noreferrer')
    setTimeout(() => {
      copyDone.value = false
    }, 2000)
  } catch (e) {
    sendError.value = e.message || '复制失败，请重试'
  } finally {
    copying.value = false
  }
}

async function send() {
  const text = draft.value.trim()
  if (!text || loading.value || loadError.value || !historyId.value) return

  messages.value.push({ role: 'user', content: text, animateIn: true })
  draft.value = ''
  sendError.value = ''
  loading.value = true
  pending.value = { thinking: '' }
  await scrollToBottom()

  const apiMsgs = toApiMessages(messages.value)

  try {
    let reply = ''
    let thinking = ''

    for await (const event of api.historyChatStream(historyId.value, apiMsgs)) {
      if (event.type === 'thinking' && event.delta) {
        pending.value.thinking += event.delta
        await scrollToBottom()
      } else if (event.type === 'content') {
        /* wait until complete before showing answer bubble */
      } else if (event.type === 'done') {
        reply = event.reply || ''
        thinking = event.thinking || pending.value.thinking || ''
      } else if (event.type === 'error') {
        throw new Error(event.error || '发送失败')
      }
    }

    pending.value = null
    await nextTick()

    messages.value.push({
      role: 'assistant',
      content: reply,
      thinking: thinking || undefined,
      thinkingCollapsed: true,
      animateIn: true,
    })
    await scrollToBottom()
  } catch (e) {
    pending.value = null
    sendError.value = e.message || '发送失败'
  } finally {
    loading.value = false
    await focusInput()
  }
}

defineExpose({ open })
</script>
