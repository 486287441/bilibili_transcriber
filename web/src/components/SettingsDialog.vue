<template>
  <dialog ref="dlg" class="settings-dialog" @cancel.prevent="close">
    <form method="dialog" class="settings-form" @submit.prevent>
      <aside class="settings-sidebar" aria-label="设置分类">
        <div class="settings-sidebar-heading">
          <span>偏好设置</span>
          <strong>设置</strong>
        </div>
        <nav class="settings-nav">
          <button
            v-for="item in sections"
            :key="item.id"
            type="button"
            :class="{ active: activeSection === item.id }"
            @click="activeSection = item.id"
          >
            <strong>{{ item.label }}</strong>
          </button>
        </nav>
      </aside>

      <section class="settings-main">
        <header class="settings-main-header">
          <div>
            <span>SETTINGS</span>
            <h2>{{ currentSection.label }}</h2>
          </div>
          <button type="button" class="settings-close" aria-label="关闭设置" @click="close">×</button>
        </header>

        <div class="settings-content ui-scroll" :class="{ 'is-prompt-section': activeSection === 'prompts' }">
          <div v-if="activeSection === 'api'" class="settings-page">
            <section class="settings-group api-settings-group">
              <div>
                <h3>DeepSeek API Key</h3>
              </div>
              <label class="api-key-field">
                <span>API Key</span>
                <input
                  v-model="deepseekApiKey"
                  type="password"
                  autocomplete="new-password"
                  spellcheck="false"
                  :placeholder="secrets.deepseek_configured ? '已配置' : '请输入 DeepSeek API Key'"
                />
              </label>
              <div class="editor-actions">
                <button type="button" :disabled="saving === 'api-key' || deepseekApiKey.trim().length < 8" @click="saveDeepSeekKey">
                  {{ saving === 'api-key' ? '保存中…' : '保存 API Key' }}
                </button>
              </div>
              <p v-if="messages.apiKey" class="storage-message" role="status">{{ messages.apiKey }}</p>
            </section>

            <section class="settings-group prompt-model-row">
              <div class="model-choice-field">
                <span class="model-choice-label">DeepSeek 模型</span>
                <div class="model-choice-options" role="radiogroup" aria-label="DeepSeek 模型">
                  <button
                    v-for="model in modelOptions"
                    :key="model.value"
                    type="button"
                    role="radio"
                    :aria-checked="settings.deepseek_model === model.value"
                    :class="{ active: settings.deepseek_model === model.value }"
                    @click="updateDeepseekModel(model.value)"
                  >{{ model.label }}</button>
                </div>
              </div>
            </section>
          </div>

          <div v-else-if="activeSection === 'prompts'" class="settings-page prompt-settings-page">
            <div class="prompt-stage-tabs" role="tablist" aria-label="Prompt 阶段">
              <button type="button" role="tab" :aria-selected="activePromptStage === 'first'" :class="{ active: activePromptStage === 'first' }" @click="activePromptStage = 'first'">
                <strong>第一阶段</strong><small>AI 优化断句</small>
              </button>
              <button type="button" role="tab" :aria-selected="activePromptStage === 'second'" :class="{ active: activePromptStage === 'second' }" @click="activePromptStage = 'second'">
                <strong>第二阶段</strong><small>AI 总结</small>
              </button>
            </div>

            <section v-if="activePromptStage === 'first'" class="prompt-workspace" role="tabpanel">
              <div class="prompt-workspace-heading">
                <div><h3>第一阶段 · AI 优化断句</h3><p>开启后使用 AI 优化断句和标点，并对明显的识别错误进行保守校正。</p></div>
                <button
                  type="button"
                  class="stage-switch"
                  role="switch"
                  :aria-checked="firstStageEnabled"
                  :disabled="saving === 'first-stage'"
                  @click="toggleFirstStage"
                >
                  <span class="stage-switch-track" aria-hidden="true"><i /></span>
                  <span>{{ firstStageEnabled ? '已启用' : '已关闭' }}</span>
                </button>
              </div>
              <textarea v-if="firstStageEnabled" class="ui-scroll" v-model="advanced.transcript_correction_prompt" rows="12" spellcheck="false" aria-label="第一阶段 AI 优化断句 Prompt" />
              <div v-else class="second-stage-disabled-note">
                关闭后不使用 AI 优化断句，将保留语音转写原有标点，只进行本地规则排版，然后直接发布到飞书。
              </div>
              <div v-if="firstStageEnabled" class="prompt-workspace-footer">
                <div class="editor-actions">
                  <button type="button" :disabled="saving === 'correction'" @click="saveCorrectionPrompt">{{ saving === 'correction' ? '保存中…' : '保存' }}</button>
                  <button type="button" class="ghost" @click="restoreCorrectionPrompt">恢复默认</button>
                </div>
                <p v-if="messages.correction" class="storage-message" role="status">{{ messages.correction }}</p>
              </div>
              <p v-if="messages.correction && !firstStageEnabled" class="storage-message second-stage-message" role="status">{{ messages.correction }}</p>
            </section>

            <section v-else class="prompt-workspace" role="tabpanel">
              <div class="prompt-workspace-heading">
                <div><h3>第二阶段 · AI 总结</h3><p>开启后使用 AI 生成视频总结、内容目录和章节结构。</p></div>
                <button
                  type="button"
                  class="stage-switch"
                  role="switch"
                  :aria-checked="secondStageEnabled"
                  :disabled="saving === 'second-stage' || !firstStageEnabled"
                  @click="toggleSecondStage"
                >
                  <span class="stage-switch-track" aria-hidden="true"><i /></span>
                  <span>{{ secondStageEnabled ? '已启用' : '已关闭' }}</span>
                </button>
              </div>
              <textarea v-if="firstStageEnabled && secondStageEnabled" class="ui-scroll" v-model="advanced.polish_prompt_template" rows="12" spellcheck="false" aria-label="第二阶段 AI 总结 Prompt" />
              <div v-else-if="!firstStageEnabled" class="second-stage-disabled-note">
                第一阶段关闭时为快速模式，不调用 AI，因此也不会生成第二阶段的 AI 总结。当前设置会保留到重新启用第一阶段后使用。
              </div>
              <div v-else class="second-stage-disabled-note">
                关闭后不生成 AI 总结，第一阶段处理完成后将直接生成文章并发布。
              </div>
              <p v-if="messages.polish && !secondStageEnabled" class="storage-message second-stage-message" role="status">{{ messages.polish }}</p>
              <div v-if="firstStageEnabled && secondStageEnabled" class="prompt-workspace-footer">
                <div class="editor-actions">
                  <button type="button" :disabled="saving === 'polish'" @click="savePolishPrompt">{{ saving === 'polish' ? '保存中…' : '保存 AI 总结设置' }}</button>
                  <button type="button" class="ghost" @click="restorePolishPrompt">恢复默认</button>
                </div>
                <p v-if="messages.polish" class="storage-message" role="status">{{ messages.polish }}</p>
              </div>
            </section>
          </div>

          <div v-else class="settings-page activity-log-page">
            <div class="activity-log-toolbar">
              <div>
                <strong>运行动态</strong>
                <span>最近 {{ activityItems.length }} 条</span>
              </div>
              <button type="button" class="ghost" :disabled="activityLoading" @click="refreshActivityLogs">
                {{ activityLoading ? '刷新中…' : '刷新' }}
              </button>
            </div>

            <div class="activity-timeline ui-scroll" aria-live="polite">
              <article v-for="item in activityItems" :key="item.id" class="activity-event" :data-level="item.level">
                <time :datetime="item.timestamp">{{ formatActivityTime(item.timestamp) }}</time>
                <div class="activity-rail" aria-hidden="true"><span /></div>
                <component
                  :is="item.timing ? 'button' : 'div'"
                  class="activity-event-body"
                  :class="{ 'activity-event-trigger': item.timing }"
                  :type="item.timing ? 'button' : undefined"
                  :aria-label="item.timing ? `查看${item.title || '任务'}的耗时明细` : undefined"
                  @click="item.timing && openTiming(item)"
                >
                  <div class="activity-event-heading">
                    <strong>{{ item.message }}</strong>
                    <span>{{ item.timing ? '查看耗时' : activityLevelLabel(item.level) }}</span>
                  </div>
                  <p v-if="item.detail">{{ item.detail }}</p>
                  <small v-if="item.title">{{ item.title }}</small>
                </component>
              </article>
              <div v-if="!activityLoading && !activityItems.length" class="activity-log-empty">
                暂无运行日志，新任务开始后会在这里显示关键步骤。
              </div>
              <div v-if="activityError" class="activity-log-error" role="alert">{{ activityError }}</div>
            </div>
          </div>
        </div>
      </section>
    </form>
  </dialog>
  <TaskTimingDialog ref="timingDialog" />
</template>

<script setup>
import { computed, onUnmounted, reactive, ref, watch } from 'vue'
import { api } from '../api.js'
import { useModalAnimation } from '../composables/useModalAnimation.js'
import TaskTimingDialog from './TaskTimingDialog.vue'

const props = defineProps({
  settings: { type: Object, required: true },
  secrets: { type: Object, required: true },
})

const emit = defineEmits(['refresh'])
const dlg = ref(null)
const { openModal, closeModal } = useModalAnimation()
const activeSection = ref('api')
const activePromptStage = ref('first')
const deepseekApiKey = ref('')
const saving = ref('')
const activityItems = ref([])
const activityLoading = ref(false)
const activityError = ref('')
const timingDialog = ref(null)
let activityTimer = null
const sections = [
  { id: 'api', label: 'API 配置', description: 'DeepSeek 密钥与模型' },
  { id: 'prompts', label: 'Prompt 调整', description: '两阶段处理指令' },
  { id: 'logs', label: '运行日志', description: '查看任务进展与异常' },
]
const modelOptions = [
  { value: 'deepseek-v4-flash', label: 'DeepSeek V4 Flash' },
  { value: 'deepseek-v4-pro', label: 'DeepSeek V4 Pro' },
]
const currentSection = computed(() => sections.find((item) => item.id === activeSection.value) || sections[0])
const advancedDefaults = reactive({
  transcript_correction_prompt: '',
  polish_prompt_template: '',
})
const advanced = reactive({ ...advancedDefaults })
const messages = reactive({ apiKey: '', correction: '', polish: '' })
const firstStageEnabled = ref(true)
const secondStageEnabled = ref(true)

function syncPromptDrafts() {
  advanced.transcript_correction_prompt = props.settings.transcript_correction_prompt || advancedDefaults.transcript_correction_prompt || ''
  advanced.polish_prompt_template = props.settings.polish_prompt_template || advancedDefaults.polish_prompt_template || ''
  firstStageEnabled.value = props.settings.first_stage_enabled !== false
  secondStageEnabled.value = props.settings.second_stage_enabled !== false
}

async function loadPromptDefaults() {
  try {
    Object.assign(advancedDefaults, await api.settingsDefaults())
    syncPromptDrafts()
  } catch {
    // Existing saved prompts remain editable if defaults cannot be loaded.
  }
}

function open() {
  deepseekApiKey.value = ''
  messages.apiKey = ''
  messages.correction = ''
  messages.polish = ''
  syncPromptDrafts()
  openModal(dlg.value)
  loadPromptDefaults()
  if (activeSection.value === 'logs') refreshActivityLogs()
}

async function close() {
  deepseekApiKey.value = ''
  stopActivityPolling()
  await closeModal(dlg.value)
}

function stopActivityPolling() {
  if (activityTimer != null) clearTimeout(activityTimer)
  activityTimer = null
}

async function refreshActivityLogs() {
  if (activityLoading.value) return
  activityLoading.value = true
  activityError.value = ''
  try {
    const data = await api.activityLogs(200)
    activityItems.value = data.items || []
  } catch (error) {
    activityError.value = error.message || '运行日志加载失败'
  } finally {
    activityLoading.value = false
    stopActivityPolling()
    if (activeSection.value === 'logs' && dlg.value?.open) {
      activityTimer = setTimeout(refreshActivityLogs, 2500)
    }
  }
}

function formatActivityTime(value) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '--:--:--'
  return new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
  }).format(date)
}

function activityLevelLabel(level) {
  return ({ success: '完成', warning: '提醒', error: '异常', info: '进行中' })[level] || '信息'
}

watch(activeSection, (section) => {
  stopActivityPolling()
  if (section === 'logs' && dlg.value?.open) refreshActivityLogs()
})

onUnmounted(stopActivityPolling)

async function saveDeepSeekKey() {
  const value = deepseekApiKey.value.trim()
  if (saving.value || value.length < 8) return
  saving.value = 'api-key'
  messages.apiKey = ''
  try {
    await api.updateDeepSeekKey(value)
    deepseekApiKey.value = ''
    messages.apiKey = 'API Key 已安全保存到本机。'
    emit('refresh')
  } catch (error) {
    messages.apiKey = error.message || 'API Key 保存失败'
  } finally {
    saving.value = ''
  }
}

async function updateDeepseekModel(model) {
  if (model === props.settings.deepseek_model) return
  await api.updateSettings({ deepseek_model: model })
  emit('refresh')
}

function openTiming(item) {
  timingDialog.value?.open(item)
}

async function toggleSecondStage() {
  if (saving.value) return
  const previous = secondStageEnabled.value
  secondStageEnabled.value = !previous
  saving.value = 'second-stage'
  messages.polish = ''
  try {
    await api.updateSettings({ second_stage_enabled: secondStageEnabled.value })
    emit('refresh')
  } catch (error) {
    secondStageEnabled.value = previous
    messages.polish = error.message || '第二阶段设置保存失败'
  } finally {
    saving.value = ''
  }
}

async function toggleFirstStage() {
  if (saving.value) return
  const previous = firstStageEnabled.value
  firstStageEnabled.value = !previous
  saving.value = 'first-stage'
  messages.correction = ''
  try {
    await api.updateSettings({ first_stage_enabled: firstStageEnabled.value })
    messages.correction = firstStageEnabled.value
      ? '第一阶段已启用，后续任务将使用 DeepSeek 校对。'
      : '快速模式已启用，后续任务将保留 ASR 标点并进行本地排版。'
    emit('refresh')
  } catch (error) {
    firstStageEnabled.value = previous
    messages.correction = error.message || '第一阶段设置保存失败'
  } finally {
    saving.value = ''
  }
}

async function savePrompt(kind, payload) {
  if (saving.value) return
  saving.value = kind
  messages[kind] = ''
  try {
    await api.updateSettings(payload)
    messages[kind] = '已保存，后续任务将使用新设置。'
    emit('refresh')
  } catch (error) {
    messages[kind] = error.message || '保存失败'
  } finally {
    saving.value = ''
  }
}

function saveCorrectionPrompt() {
  return savePrompt('correction', { transcript_correction_prompt: advanced.transcript_correction_prompt })
}

function savePolishPrompt() {
  return savePrompt('polish', { polish_prompt_template: advanced.polish_prompt_template })
}

async function restoreCorrectionPrompt() {
  if (!advancedDefaults.transcript_correction_prompt) await loadPromptDefaults()
  advanced.transcript_correction_prompt = advancedDefaults.transcript_correction_prompt
  await saveCorrectionPrompt()
}

async function restorePolishPrompt() {
  if (!advancedDefaults.polish_prompt_template) await loadPromptDefaults()
  advanced.polish_prompt_template = advancedDefaults.polish_prompt_template
  await savePolishPrompt()
}

defineExpose({ open })
</script>
