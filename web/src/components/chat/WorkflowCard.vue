<script setup lang="ts">
// 工作流匹配卡：左边强调色竖线 + 标题 + 步骤列表。
// 步骤状态：running(spinner primary) / ok(✓ success) / fail(✗ error) / todo(· muted)。
// 字符仅用已验证集合：✓ + spinner，无 ⚡（二进制零命中）。
import { ref, onMounted, onUnmounted } from 'vue'
import { SPINNER_FRAMES } from '@/lib/workingVerbs'

export interface WorkflowStep {
  display_name: string
  status: 'running' | 'ok' | 'fail' | 'todo'
}

const props = defineProps<{
  title: string
  steps: WorkflowStep[]
}>()

const spinner = ref(SPINNER_FRAMES[0])
let timer: number | null = null

onMounted(() => {
  if (props.steps.some((s) => s.status === 'running')) {
    timer = window.setInterval(() => {
      spinner.value = SPINNER_FRAMES[(SPINNER_FRAMES.indexOf(spinner.value) + 1) % SPINNER_FRAMES.length]
    }, 100)
  }
})
onUnmounted(() => {
  if (timer != null) window.clearInterval(timer)
})
</script>

<template>
  <div
    class="rounded-r-lg border-l-2 border-primary bg-primary/10 px-2.5 py-1.5 text-[13px]"
  >
    <div class="font-medium text-foreground">匹配工作流：{{ props.title }}</div>
    <div class="mt-1 space-y-0.5 font-mono text-xs">
      <div
        v-for="(s, i) in props.steps"
        :key="i"
        :class="{
          'text-primary': s.status === 'running',
          'text-[hsl(var(--ring))]': s.status === 'ok',
          'text-destructive': s.status === 'fail',
          'text-muted-foreground': s.status === 'todo',
        }"
      >
        <span v-if="s.status === 'running'" class="inline-block w-[1ch]">{{ spinner }}</span>
        <span v-else-if="s.status === 'ok'">✓</span>
        <span v-else-if="s.status === 'fail'">✗</span>
        <span v-else>·</span>
        <span class="ml-1.5">{{ s.display_name }}</span>
      </div>
    </div>
  </div>
</template>
