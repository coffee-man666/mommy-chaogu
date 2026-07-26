<script setup lang="ts">
// Kimi 风顶部状态栏：品牌 · 连接点 · 市场阶段 · 时钟
// 连接点用 Kimi 语义 token 实色（success/warning/error），不用 emoji。
import { ref, onMounted, onUnmounted } from 'vue'
import { marketPhase, shanghaiClock, type MarketPhase } from '@/lib/marketPhase'

const props = defineProps<{
  /** WS / 网络连接状态 → 决定圆点颜色 */
  connection: 'live' | 'degraded' | 'offline' | 'idle'
  brand?: string
}>()

const clock = ref('--:--:--')
const phase = ref<MarketPhase>('已收盘')
let timer: number | null = null

function tick() {
  clock.value = shanghaiClock()
  phase.value = marketPhase()
}

const dotClass = (c: typeof props.connection) => {
  switch (c) {
    case 'live':
      return 'bg-primary' // Kimi primary 蓝；live 用主色
    case 'degraded':
      return 'bg-[hsl(var(--ring))]' // 警告色
    case 'offline':
      return 'bg-destructive'
    default:
      return 'bg-muted-foreground/60'
  }
}

onMounted(() => {
  tick()
  timer = window.setInterval(tick, 1000)
})
onUnmounted(() => {
  if (timer != null) window.clearInterval(timer)
})
</script>

<template>
  <div
    class="sticky top-0 z-20 flex items-center gap-2.5 border-b border-border bg-background/90 px-3.5 py-2 font-mono text-xs text-muted-foreground backdrop-blur"
  >
    <span class="font-semibold text-foreground">{{ props.brand ?? 'mommy-chaogu' }}</span>
    <span class="inline-block h-2 w-2 rounded-full" :class="dotClass(props.connection)" />
    <span class="text-primary">{{ phase }}</span>
    <span class="ml-auto tabular-nums">{{ clock }}</span>
  </div>
</template>
