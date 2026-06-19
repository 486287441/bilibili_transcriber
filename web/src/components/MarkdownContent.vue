<template>
  <div class="markdown-body" :class="{ 'markdown-dark': dark }" v-html="html" />
</template>

<script setup>
import { computed } from 'vue'
import { renderMarkdown } from '../markdown.js'

const props = defineProps({
  content: { type: String, default: '' },
  dark: { type: Boolean, default: false },
})

const html = computed(() => renderMarkdown(props.content))
</script>
