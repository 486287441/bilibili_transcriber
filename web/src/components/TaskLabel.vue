<template>
  <div class="task-label">
    <a
      v-if="link"
      class="task-url"
      :href="url"
      target="_blank"
      rel="noopener"
      :title="url"
    >{{ url }}</a>
    <span v-else class="task-url" :title="url">{{ url }}</span>
    <div v-if="title" class="task-title">{{ title }}</div>
  </div>
</template>

<script setup>
defineProps({
  url: { type: String, required: true },
  title: { type: String, default: null },
  link: { type: Boolean, default: false },
})
</script>
