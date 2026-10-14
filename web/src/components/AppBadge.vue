<script setup>
import { computed } from 'vue'

const props = defineProps({
  text: { type: [String, Number], default: '' },
  tone: { type: String, default: 'muted' }, // muted | ok | warn | danger | primary
})

const classes = computed(() => ['badge', props.tone !== 'muted' ? `badge-${props.tone}` : ''])
</script>

<template>
  <span :class="classes">{{ text === '' || text === null ? '—' : text }}</span>
</template>
