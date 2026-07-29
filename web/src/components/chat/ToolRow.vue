<script setup lang="ts">
// Kimi 风工具调用行（二进制验证：不用 ⏺/⎿）。
// - 运行中：spinner(primary) + 中文名 + 函数名(text-dim)
// - 完成：✓(success，二进制+文档已验证) + 摘要(text-dim) + 耗时(muted)
// - 失败：✗(error) + 错误摘要
import { ref, onMounted, onUnmounted } from 'vue'
import { toolDisplayName, formatToolArgs, formatResultDigest } from '@/lib/toolNames'
import { SPINNER_FRAMES } from '@/lib/workingVerbs'

const props = defineProps<{
  tool: string
  args?: Record<string, unknown>
  status: 'running' | 'done' | 'fail'
  /** done 态的原始结果字符串，用于摘要（可选） */
  result?: string
  /** 失败信息 */
  error?: string
  /** 耗时 ms（done/fail） */
  elapsedMs?: number
}>()

const spinner = ref(SPINNER_FRAMES[0])
let timer: number | null = null

onMounted(() => {
  if (props.status === 'running') {
    timer = window.setInterval(() => {
      spinner.value = SPINNER_FRAMES[(SPINNER_FRAMES.indexOf(spinner.value) + 1) % SPINNER_FRAMES.length]
    }, 100)
  }
})
onUnmounted(() => {
  if (timer != null) window.clearInterval(timer)
})

const elapsedText = (ms?: number) => (ms == null ? '' : `· ${(ms / 1000).toFixed(1)}s`)
const fnDigest = `${props.tool}(${formatToolArgs(props.args)})`
const summary = () => {
  if (props.status === 'fail') return props.error || '失败'
  return formatResultDigest(props.result ?? '')
}
</script>

<template>
  <div class="pl-4 font-mono text-[13px] leading-7">
    <div v-if="status === 'running'" class="text-primary">
      <span class="inline-block w-[1ch]">{{ spinner }}</span>
      <span class="ml-1 text-foreground">{{ toolDisplayName(tool) }}</span>
      <span class="ml-1 text-muted-foreground">{{ fnDigest }}</span>
    </div>
    <div v-else-if="status === 'done'" class="text-muted-foreground">
      <span class="font-bold text-primary">✓</span>
      <span class="ml-1.5">{{ toolDisplayName(tool) }} · {{ summary() }}</span>
      <span class="ml-1.5 text-muted-foreground/80">{{ elapsedText(elapsedMs) }}</span>
    </div>
    <div v-else class="text-destructive">
      <span class="font-bold">✗</span>
      <span class="ml-1.5">{{ toolDisplayName(tool) }} · {{ summary() }}</span>
      <span class="ml-1.5 text-muted-foreground/80">{{ elapsedText(elapsedMs) }}</span>
    </div>
  </div>
</template>
