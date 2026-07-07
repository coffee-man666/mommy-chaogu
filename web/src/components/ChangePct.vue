<script setup lang="ts">
import { computed } from 'vue'
import { fmtPct, changeColor } from '../utils/format'

const props = defineProps<{
  value: string | number | null | undefined
}>()

const color = computed(() => changeColor(props.value))
const text = computed(() => fmtPct(props.value))
</script>

<template>
  <span
    :style="{
      color,
      background: color === '#666' ? 'transparent' : color + '15',
      padding: '1px 6px',
      borderRadius: '4px',
      fontSize: '12px',
      fontWeight: 600,
    }"
  >{{ text }}</span>
</template>
