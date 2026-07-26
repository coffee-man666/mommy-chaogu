<script setup lang="ts">
// 工作中指示：spinner(primary) + A股动词 + 耗时。
// token 数待后端 done 携带 usage 时再加（先隐藏）。
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { SPINNER_FRAMES } from '@/lib/workingVerbs'

const props = defineProps<{
  verb?: string
  /** 已经经过的毫秒数 */
  elapsedMs: number
  tokens?: number
}>()

const spinner = ref(SPINNER_FRAMES[0])
let timer: number | null = null

onMounted(() => {
  timer = window.setInterval(() => {
    spinner.value = SPINNER_FRAMES[(SPINNER_FRAMES.indexOf(spinner.value) + 1) % SPINNER_FRAMES.length]
  }, 100)
})
onUnmounted(() => {
  if (timer != null) window.clearInterval(timer)
})

const elapsedText = computed(() => `${(props.elapsedMs / 1000).toFixed(1)}s`)
const tokenText = computed(() => {
  if (props.tokens == null) return ''
  const k = props.tokens >= 1000 ? `${(props.tokens / 1000).toFixed(1)}k` : `${props.tokens}`
  return ` · ↓ ${k} tokens`
})
</script>

<template>
  <div class="flex items-center gap-2 px-3.5 pt-1 font-mono text-xs text-muted-foreground">
    <span class="text-primary">{{ spinner }}</span>
    <span>{{ props.verb ?? '处理中' }}</span>
    <span>· {{ elapsedText }}{{ tokenText }}</span>
  </div>
</template>
