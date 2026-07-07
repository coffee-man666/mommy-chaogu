<script setup lang="ts">
import { computed } from 'vue'
import { fmtPrice, changeColor } from '../utils/format'

const props = defineProps<{
  value: string | number | null | undefined
  changePct?: string | number | null | undefined
  size?: 'sm' | 'md' | 'lg'
}>()

const color = computed(() =>
  props.changePct != null ? changeColor(props.changePct) : '#333'
)
const text = computed(() => fmtPrice(props.value))
const fontSize = computed(() =>
  props.size === 'lg' ? '20px' : props.size === 'sm' ? '13px' : '15px'
)
</script>

<template>
  <span :style="{ color, fontSize, fontWeight: 600 }">{{ text }}</span>
</template>
