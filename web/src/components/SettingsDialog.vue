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
            <small>{{ item.description }}</small>
          </button>
        </nav>
      </aside>

      <section class="settings-main">
        <header class="settings-main-header">
          <div>
            <span>SETTINGS</span>
            <h2>{{ currentSection.label }}</h2>
            <p>{{ currentSection.description }}</p>
          </div>
          <button type="button" class="settings-close" aria-label="关闭设置" @click="close">×</button>
        </header>

        <div class="settings-content ui-scroll">
          <div v-if="activeSection === 'api'" class="settings-page">
            <section class="settings-group api-settings-group">
              <div>
                <h3>DeepSeek API Key</h3>
                <p class="editor-hint">密钥只保存在本机项目的 <code>.env</code>，页面不会回显已保存的内容。</p>
              </div>
              <label class="api-key-field">
                <span>API Key</span>
                <input
                  v-model="deepseekApiKey"
                  type="password"
                  autocomplete="new-password"
                  spellcheck="false"
                  :placeholder="secrets.deepseek_configured ? '已配置；输入新 Key 可替换' : '请输入 DeepSeek API Key'"
                />
              </label>
              <div class="editor-actions">
                <button type="button" :disabled="saving === 'api-key' || deepseekApiKey.trim().length < 8" @click="saveDeepSeekKey">
                  {{ saving === 'api-key' ? '保存中…' : '保存 API Key' }}
                </button>
                <span class="api-config-state" :data-configured="secrets.deepseek_configured">
                  {{ secrets.deepseek_configured ? '已配置' : '尚未配置' }}
                </span>
              </div>
              <p v-if="messages.apiKey" class="storage-message" role="status">{{ messages.apiKey }}</p>
            </section>

            <section class="settings-group prompt-model-row">
              <label>
                DeepSeek 模型
                <select :value="settings.deepseek_model" @change="updateDeepseekModel">
                  <option value="deepseek-v4-flash">DeepSeek V4 Flash</option>
                  <option value="deepseek-v4-pro">DeepSeek V4 Pro</option>
                </select>
              </label>
            </section>
          </div>

          <div v-else class="settings-page prompt-settings-page">
            <div class="prompt-stage-tabs" role="tablist" aria-label="Prompt 阶段">
              <button type="button" role="tab" :aria-selected="activePromptStage === 'first'" :class="{ active: activePromptStage === 'first' }" @click="activePromptStage = 'first'">
                <strong>第一阶段</strong><small>ASR 校对</small>
              </button>
              <button type="button" role="tab" :aria-selected="activePromptStage === 'second'" :class="{ active: activePromptStage === 'second' }" @click="activePromptStage = 'second'">
                <strong>第二阶段</strong><small>内容整理</small>
              </button>
            </div>

            <section v-if="activePromptStage === 'first'" class="prompt-workspace" role="tabpanel">
              <div class="prompt-workspace-heading">
                <div><h3>第一阶段 · ASR 校对 Prompt</h3><p>用于断句、恢复标点和保守纠错。</p></div>
                <span>当前 Prompt</span>
              </div>
              <textarea v-model="advanced.transcript_correction_prompt" rows="22" spellcheck="false" aria-label="第一阶段 ASR 校对 Prompt" />
              <div class="editor-actions">
                <button type="button" :disabled="saving === 'correction'" @click="saveCorrectionPrompt">{{ saving === 'correction' ? '保存中…' : '保存第一阶段' }}</button>
                <button type="button" class="ghost" @click="restoreCorrectionPrompt">恢复默认</button>
              </div>
              <p v-if="messages.correction" class="storage-message" role="status">{{ messages.correction }}</p>
            </section>

            <section v-else class="prompt-workspace" role="tabpanel">
              <div class="prompt-workspace-heading">
                <div><h3>第二阶段 · 内容整理 Prompt</h3><p>用于生成总结、目录和章节。</p></div>
                <span>当前 Prompt</span>
              </div>
              <textarea v-model="advanced.polish_prompt_template" rows="22" spellcheck="false" aria-label="第二阶段内容整理 Prompt" />
              <div class="editor-actions">
                <button type="button" :disabled="saving === 'polish'" @click="savePolishPrompt">{{ saving === 'polish' ? '保存中…' : '保存第二阶段' }}</button>
                <button type="button" class="ghost" @click="restorePolishPrompt">恢复默认</button>
              </div>
              <p v-if="messages.polish" class="storage-message" role="status">{{ messages.polish }}</p>
            </section>
          </div>
        </div>
      </section>
    </form>
  </dialog>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { api } from '../api.js'
import { useModalAnimation } from '../composables/useModalAnimation.js'

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
const sections = [
  { id: 'api', label: 'API 配置', description: 'DeepSeek 密钥与模型' },
  { id: 'prompts', label: 'Prompt 调整', description: '两阶段处理指令' },
]
const currentSection = computed(() => sections.find((item) => item.id === activeSection.value) || sections[0])
const advancedDefaults = reactive({
  transcript_correction_prompt: '',
  polish_prompt_template: '',
})
const advanced = reactive({ ...advancedDefaults })
const messages = reactive({ apiKey: '', correction: '', polish: '' })

function syncPromptDrafts() {
  advanced.transcript_correction_prompt = props.settings.transcript_correction_prompt || advancedDefaults.transcript_correction_prompt || ''
  advanced.polish_prompt_template = props.settings.polish_prompt_template || advancedDefaults.polish_prompt_template || ''
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
}

async function close() {
  deepseekApiKey.value = ''
  await closeModal(dlg.value)
}

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

async function updateDeepseekModel(event) {
  await api.updateSettings({ deepseek_model: event.target.value })
  emit('refresh')
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
