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
          <div v-if="activeSection === 'general'" class="settings-page">
            <section class="settings-group">
              <h3>任务行为</h3>
              <label class="toggle setting-row">
                <span><strong>剪贴板监听</strong><small>自动识别复制的视频链接</small></span>
                <input type="checkbox" :checked="settings.clipboard_enabled" @change="toggleClipboard" />
              </label>
              <label class="toggle setting-row">
                <span><strong>自动打开飞书</strong><small>任务完成后打开生成的文档</small></span>
                <input type="checkbox" :checked="settings.auto_open_feishu" @change="toggleAutoOpenFeishu" />
              </label>
            </section>

            <section class="settings-group">
              <h3>模型生命周期</h3>
              <label class="inline-field">
                <span>空闲卸载模型</span>
                <span><input type="number" min="1" max="1440" :value="settings.model_idle_timeout_minutes" @change="updateIdle" /> 分钟</span>
              </label>
              <div class="settings-meta-grid">
                <span>上次加载</span><strong>{{ formatModelTime(modelLifecycle.last_loaded_at) }}</strong>
                <span>上次卸载</span><strong>{{ formatModelTime(modelLifecycle.last_unloaded_at) }}</strong>
                <span>当前显存</span><strong>{{ formatGpuMemory(modelLifecycle) }}</strong>
              </div>
            </section>
          </div>

          <div v-else-if="activeSection === 'prompts'" class="settings-page prompt-settings-page">
            <section class="settings-group prompt-model-row">
              <label>
                DeepSeek 模型
                <select :value="settings.deepseek_model" @change="updateDeepseekModel">
                  <option value="deepseek-v4-pro">DeepSeek V4 Pro</option>
                  <option value="deepseek-v4-flash">DeepSeek V4 Flash</option>
                </select>
              </label>
            </section>

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
                <div><h3>第一阶段 · ASR 校对 Prompt</h3><p>用于断句、恢复标点和保守纠错。支持直接编辑 Markdown。</p></div>
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
                <div><h3>第二阶段 · 内容整理 Prompt</h3><p>用于生成推荐指数、总结、目录和章节。支持直接编辑 Markdown。</p></div>
                <span>当前 Prompt</span>
              </div>
              <p class="editor-hint"><code v-pre>{{recommendation_criteria}}</code> 是推荐标准插入位置；删除后会自动追加到末尾。</p>
              <textarea v-model="advanced.polish_prompt_template" rows="22" spellcheck="false" aria-label="第二阶段内容整理 Prompt" />
              <div class="editor-actions">
                <button type="button" :disabled="saving === 'polish'" @click="savePolishPrompt">{{ saving === 'polish' ? '保存中…' : '保存第二阶段' }}</button>
                <button type="button" class="ghost" @click="restorePolishPrompt">恢复默认</button>
              </div>
              <p v-if="messages.polish" class="storage-message" role="status">{{ messages.polish }}</p>

              <details class="recommendation-editor">
                <summary>推荐指数判断标准</summary>
                <p class="editor-hint">作为第二阶段 Prompt 的独立规则块，可单独调整。</p>
                <textarea v-model="advanced.recommendation_criteria" rows="16" spellcheck="false" aria-label="推荐判断标准" />
                <div class="editor-actions">
                  <button type="button" :disabled="saving === 'recommendation'" @click="saveRecommendation">{{ saving === 'recommendation' ? '保存中…' : '保存推荐标准' }}</button>
                  <button type="button" class="ghost" @click="restoreRecommendation">恢复默认</button>
                </div>
                <p v-if="messages.recommendation" class="storage-message" role="status">{{ messages.recommendation }}</p>
              </details>
            </section>
          </div>

          <div v-else-if="activeSection === 'publishing'" class="settings-page">
            <section class="settings-group prompt-workspace">
              <h3>飞书文档格式</h3>
              <p class="editor-hint">标题支持 <code v-pre>{{date}}</code>、<code v-pre>{{datetime}}</code>、<code v-pre>{{title}}</code>。</p>
              <label class="template-field">飞书文档标题模板<input v-model="advanced.feishu_title_template" type="text" spellcheck="false" /></label>
              <p class="editor-hint">正文必须保留 <code v-pre>{{body}}</code>，还支持标题、链接、转写时间、日期和统计信息占位符。</p>
              <textarea v-model="advanced.feishu_document_template" rows="18" spellcheck="false" aria-label="飞书文档正文模板" />
              <div class="editor-actions">
                <button type="button" :disabled="saving === 'feishu'" @click="saveFeishuTemplates">{{ saving === 'feishu' ? '保存中…' : '保存飞书格式' }}</button>
                <button type="button" class="ghost" @click="restoreFeishuTemplates">恢复默认</button>
              </div>
              <p v-if="messages.feishu" class="storage-message">{{ messages.feishu }}</p>
            </section>
          </div>

          <div v-else class="settings-page">
            <section class="settings-group storage-section">
              <h3>本地整理稿</h3>
              <div>共 {{ storageStats.count }} 篇，约 {{ formatSize(storageStats.bytes) }}</div>
              <p class="storage-hint">清除后追问将不可用，需重新处理视频后才会再次生成。</p>
              <button type="button" class="danger" :disabled="clearing || storageStats.count === 0" @click="clearPolished">{{ clearing ? '清除中…' : '清除本地整理稿' }}</button>
              <p v-if="clearMessage" class="storage-message">{{ clearMessage }}</p>
            </section>
            <section class="settings-group">
              <h3>运行与密钥</h3>
              <div class="settings-meta-grid">
                <span>DeepSeek</span><strong>{{ secrets.deepseek_configured ? '已配置' : '未配置' }}</strong>
                <span>飞书</span><strong>{{ secrets.feishu_configured ? '已配置' : '未配置' }}</strong>
              </div>
              <p class="storage-hint">密钥为只读状态，如需修改请编辑项目的 .env 文件。</p>
              <button type="button" @click="openLogs">查看运行日志</button>
            </section>
          </div>
        </div>
      </section>
    </form>
    <LogViewerDialog ref="logViewerRef" />
  </dialog>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { api } from '../api.js'
import { useModalAnimation } from '../composables/useModalAnimation.js'
import LogViewerDialog from './LogViewerDialog.vue'

const DEFAULT_TRANSCRIPT_CORRECTION_PROMPT = `这是语音识别生成的无标点转写稿，其中可能存在错字、同音近音误识别、漏字、多字和专有名词识别错误。

请根据上下文恢复说话人最可能的原话：

* 重新断句、添加标点并合理分段；
* 修正能够从语义、语法或上下文明确判断的语音识别错误；
* 忠实保留原意、措辞和口语风格，不进行润色或内容改写；
* 不得仅为了让句子更优美而修改文字；无法可靠判断时保留原文。

只输出校对后的完整转写稿。`

const props = defineProps({
  settings: { type: Object, required: true },
  secrets: { type: Object, required: true },
})

const emit = defineEmits(['refresh'])

const dlg = ref(null)
const logViewerRef = ref(null)
const { openModal, closeModal } = useModalAnimation()
const activeSection = ref('general')
const activePromptStage = ref('first')
const sections = [
  { id: 'general', label: '常规', description: '任务行为与模型状态' },
  { id: 'prompts', label: 'AI 与 Prompt', description: '两阶段处理指令' },
  { id: 'publishing', label: '文档输出', description: '飞书标题与正文格式' },
  { id: 'data', label: '数据与运行', description: '本地稿件、日志与密钥' },
]
const currentSection = computed(() => sections.find((item) => item.id === activeSection.value) || sections[0])
const storageStats = ref({ count: 0, bytes: 0 })
const modelLifecycle = ref({ last_loaded_at: null, last_unloaded_at: null })
const clearing = ref(false)
const clearMessage = ref('')
const saving = ref('')
const advancedDefaults = reactive({
  recommendation_criteria: '',
  transcript_correction_prompt: '',
  polish_prompt_template: '',
  feishu_title_template: '',
  feishu_document_template: '',
})
const advanced = reactive({ ...advancedDefaults })
const messages = reactive({ correction: '', recommendation: '', polish: '', feishu: '' })

function formatSize(bytes) {
  if (!bytes) return '0 B'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function formatModelTime(iso) {
  if (!iso) return '暂无记录'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '暂无记录'
  const month = d.getMonth() + 1
  const day = d.getDate()
  const hour = String(d.getHours()).padStart(2, '0')
  const minute = String(d.getMinutes()).padStart(2, '0')
  return `${month}月${day}日 ${hour}:${minute}`
}

function formatGpuMemory(status) {
  if (!status?.gpu_available) return '不适用（CPU 模式）'
  const allocated = status.gpu_memory_allocated_bytes ?? 0
  const total = status.gpu_memory_total_bytes
  if (total) return `${formatSize(allocated)} / ${formatSize(total)}`
  return formatSize(allocated)
}

async function loadModelLifecycle() {
  try {
    const s = await api.status()
    modelLifecycle.value = {
      last_loaded_at: s.model_last_loaded_at,
      last_unloaded_at: s.model_last_unloaded_at,
      gpu_available: s.gpu_available,
      gpu_memory_allocated_bytes: s.gpu_memory_allocated_bytes,
      gpu_memory_reserved_bytes: s.gpu_memory_reserved_bytes,
      gpu_memory_total_bytes: s.gpu_memory_total_bytes,
      gpu_device: s.gpu_device,
    }
  } catch {
    modelLifecycle.value = {
      last_loaded_at: null,
      last_unloaded_at: null,
      gpu_available: false,
      gpu_memory_allocated_bytes: null,
      gpu_memory_reserved_bytes: null,
      gpu_memory_total_bytes: null,
      gpu_device: null,
    }
  }
}

async function loadStorageStats() {
  try {
    storageStats.value = await api.polishedStorage()
  } catch {
    storageStats.value = { count: 0, bytes: 0 }
  }
}

function syncAdvancedDrafts() {
  advanced.recommendation_criteria = props.settings.recommendation_criteria || ''
  advanced.transcript_correction_prompt =
    props.settings.transcript_correction_prompt ||
    advancedDefaults.transcript_correction_prompt ||
    DEFAULT_TRANSCRIPT_CORRECTION_PROMPT
  advanced.polish_prompt_template = props.settings.polish_prompt_template || ''
  advanced.feishu_title_template = props.settings.feishu_title_template || ''
  advanced.feishu_document_template = props.settings.feishu_document_template || ''
}

async function loadAdvancedDefaults() {
  try {
    Object.assign(advancedDefaults, await api.settingsDefaults())
    if (!props.settings.transcript_correction_prompt) {
      advanced.transcript_correction_prompt =
        advancedDefaults.transcript_correction_prompt || DEFAULT_TRANSCRIPT_CORRECTION_PROMPT
    }
  } catch {
    if (!advanced.transcript_correction_prompt) {
      advanced.transcript_correction_prompt = DEFAULT_TRANSCRIPT_CORRECTION_PROMPT
    }
  }
}

function open() {
  clearMessage.value = ''
  messages.correction = ''
  messages.recommendation = ''
  messages.polish = ''
  messages.feishu = ''
  syncAdvancedDrafts()
  openModal(dlg.value)
  loadStorageStats()
  loadModelLifecycle()
  loadAdvancedDefaults()
}

async function close() {
  await closeModal(dlg.value)
}

function openLogs() {
  logViewerRef.value?.open()
}

async function toggleClipboard(ev) {
  await api.updateSettings({ clipboard_enabled: ev.target.checked })
  emit('refresh')
}

async function toggleAutoOpenFeishu(ev) {
  await api.updateSettings({ auto_open_feishu: ev.target.checked })
  emit('refresh')
}

async function updateDeepseekModel(ev) {
  await api.updateSettings({ deepseek_model: ev.target.value })
  emit('refresh')
}

async function updateIdle(ev) {
  const v = parseInt(ev.target.value, 10)
  if (v >= 1) {
    await api.updateSettings({ model_idle_timeout_minutes: v })
    emit('refresh')
  }
}

async function saveAdvanced(kind, payload) {
  if (saving.value) return false
  saving.value = kind
  messages[kind] = ''
  try {
    await api.updateSettings(payload)
    messages[kind] = '已保存，后续任务将使用新设置。'
    emit('refresh')
    return true
  } catch (e) {
    messages[kind] = e.message || '保存失败'
    return false
  } finally {
    saving.value = ''
  }
}

function saveRecommendation() {
  return saveAdvanced('recommendation', {
    recommendation_criteria: advanced.recommendation_criteria,
  })
}

function saveCorrectionPrompt() {
  return saveAdvanced('correction', {
    transcript_correction_prompt: advanced.transcript_correction_prompt,
  })
}

function savePolishPrompt() {
  return saveAdvanced('polish', {
    polish_prompt_template: advanced.polish_prompt_template,
  })
}

function saveFeishuTemplates() {
  return saveAdvanced('feishu', {
    feishu_title_template: advanced.feishu_title_template,
    feishu_document_template: advanced.feishu_document_template,
  })
}

async function restoreRecommendation() {
  if (!advancedDefaults.recommendation_criteria) await loadAdvancedDefaults()
  advanced.recommendation_criteria = advancedDefaults.recommendation_criteria
  await saveRecommendation()
}

async function restoreCorrectionPrompt() {
  if (!advancedDefaults.transcript_correction_prompt) await loadAdvancedDefaults()
  advanced.transcript_correction_prompt = advancedDefaults.transcript_correction_prompt
  await saveCorrectionPrompt()
}

async function restorePolishPrompt() {
  if (!advancedDefaults.polish_prompt_template) await loadAdvancedDefaults()
  advanced.polish_prompt_template = advancedDefaults.polish_prompt_template
  await savePolishPrompt()
}

async function restoreFeishuTemplates() {
  if (!advancedDefaults.feishu_document_template) await loadAdvancedDefaults()
  advanced.feishu_title_template = advancedDefaults.feishu_title_template
  advanced.feishu_document_template = advancedDefaults.feishu_document_template
  await saveFeishuTemplates()
}

async function clearPolished() {
  if (clearing.value || storageStats.value.count === 0) return
  if (!window.confirm(`确定清除 ${storageStats.value.count} 篇本地整理稿吗？`)) return

  clearing.value = true
  clearMessage.value = ''
  try {
    const result = await api.clearPolishedStorage()
    clearMessage.value = `已清除 ${result.deleted_count} 篇，释放约 ${formatSize(result.freed_bytes)}`
    await loadStorageStats()
  } catch (e) {
    clearMessage.value = e.message || '清除失败'
  } finally {
    clearing.value = false
  }
}

defineExpose({ open })
</script>
