<template>
  <dialog ref="dlg" class="recommendation-dialog" @cancel.prevent="close">
    <div class="recommendation-dialog-shell">
      <header class="recommendation-dialog-head">
        <div>
          <h2>推荐评估</h2>
          <p v-if="title">{{ title }}</p>
        </div>
        <button type="button" class="ghost" @click="close">关闭</button>
      </header>

      <div v-if="recommendation" class="recommendation-dialog-body">
        <div class="recommendation-result" :data-grade="recommendation.grade">
          <div>
            <span>结论</span>
            <strong>{{ recommendation.verdict || verdictFor(recommendation.grade) }}</strong>
          </div>
          <div>
            <span>等级</span>
            <strong>{{ recommendation.grade }}级</strong>
          </div>
          <div>
            <span>{{ recommendation.is_dual_score ? '内容价值' : '分数' }}</span>
            <strong>{{ Math.round(recommendation.content_score ?? recommendation.score) }}分</strong>
          </div>
          <div v-if="recommendation.is_dual_score">
            <span>原片增量</span>
            <strong>{{ Math.round(recommendation.incremental_score) }}分</strong>
          </div>
        </div>

        <dl class="recommendation-details">
          <div v-if="recommendation.is_dual_score">
            <dt>内容类型</dt>
            <dd>{{ recommendation.content_type || '未分类' }}</dd>
          </div>
          <div v-if="recommendation.is_dual_score">
            <dt>情绪风险</dt>
            <dd>
              {{ recommendation.negative_emotion || '未评估' }} ·
              {{ recommendation.antagonism || '未评估' }} ·
              校准扣 {{ recommendation.emotion_penalty || 0 }} 分
              <template v-if="recommendation.base_content_score != null">
                （基础 {{ Math.round(recommendation.base_content_score) }} 分）
              </template>
            </dd>
          </div>
          <div>
            <dt>观看建议</dt>
            <dd>{{ recommendation.advice || '—' }}</dd>
          </div>
          <div>
            <dt>广告判断</dt>
            <dd>{{ recommendation.advertising || '未评估' }}</dd>
          </div>
          <div v-if="recommendation.is_dual_score">
            <dt>内容价值依据</dt>
            <dd>{{ recommendation.content_reason || '暂无内容价值依据' }}</dd>
          </div>
          <div v-if="recommendation.is_dual_score">
            <dt>原片增量依据</dt>
            <dd>{{ recommendation.incremental_reason || '暂无原片增量依据' }}</dd>
          </div>
          <div v-if="recommendation.is_dual_score">
            <dt>情绪风险依据</dt>
            <dd>{{ recommendation.emotion_reason || '暂无情绪风险依据' }}</dd>
          </div>
          <div v-if="recommendation.is_dual_score">
            <dt>综合判断</dt>
            <dd>{{ recommendation.overall_reason || recommendationReason }}</dd>
          </div>
          <div v-else>
            <dt>打分依据</dt>
            <dd>{{ scoringReason }}</dd>
          </div>
          <div v-if="!recommendation.is_dual_score">
            <dt>推荐理由</dt>
            <dd>{{ recommendationReason }}</dd>
          </div>
        </dl>
      </div>
    </div>
  </dialog>
</template>

<script setup>
import { computed, ref } from 'vue'

const dlg = ref(null)
const title = ref('')
const recommendation = ref(null)

const scoringReason = computed(() =>
  recommendation.value?.scoring_reason || recommendation.value?.reason || '暂无详细打分依据',
)
const recommendationReason = computed(() =>
  recommendation.value?.recommendation_reason || recommendation.value?.reason || '暂无详细推荐理由',
)

function verdictFor(grade) {
  if (['S', 'A'].includes(grade)) return '推荐观看'
  if (grade === 'B') return '值得了解'
  return '可略过'
}

function open(item) {
  title.value = item?.title || ''
  recommendation.value = item?.recommendation || null
  dlg.value?.showModal()
}

function close() {
  dlg.value?.close()
}

defineExpose({ open, close })
</script>
