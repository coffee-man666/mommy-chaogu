<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { Bell, RefreshCw, Star, Target } from 'lucide-vue-next'
import { getSnapshot } from '@/api'
import { getPredictions } from '@/api/predictions'
import { recentSignals } from '@/api/signals'
import { toApiError, type ApiError } from '@/api/client'
import type { Prediction, Quote, Signal } from '@/api/types'
import { fmtPct, fmtPrice } from '@/utils/format'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import ErrorState from '@/components/ErrorState.vue'

const quotes = ref<Quote[]>([])
const predictions = ref<Prediction[]>([])
const signals = ref<Signal[]>([])
const loading = ref(true)
const errors = ref<Record<'quotes' | 'predictions' | 'signals', ApiError | null>>({
  quotes: null,
  predictions: null,
  signals: null,
})

const predictionLabels: Record<string, string> = {
  pending: '待验证',
  hit: '命中',
  missed: '未命中',
  expired: '已过期',
  unverifiable: '无法验证',
}

const severityLabels: Record<Signal['severity'], string> = {
  critical: '紧急',
  warning: '注意',
  info: '提示',
}

async function load() {
  loading.value = true
  const [snapshotResult, predictionResult, signalResult] = await Promise.allSettled([
    getSnapshot(),
    getPredictions(5),
    recentSignals(),
  ])

  if (snapshotResult.status === 'fulfilled') {
    quotes.value = snapshotResult.value.quotes.slice(0, 5)
    errors.value.quotes = null
  } else {
    errors.value.quotes = toApiError(snapshotResult.reason)
  }
  if (predictionResult.status === 'fulfilled') {
    predictions.value = predictionResult.value
    errors.value.predictions = null
  } else {
    errors.value.predictions = toApiError(predictionResult.reason)
  }
  if (signalResult.status === 'fulfilled') {
    signals.value = signalResult.value.slice(0, 5)
    errors.value.signals = null
  } else {
    errors.value.signals = toApiError(signalResult.reason)
  }
  loading.value = false
}

onMounted(() => void load())
</script>

<template>
  <aside aria-label="投研上下文" class="h-full overflow-y-auto bg-card p-4">
    <div class="mb-4 flex items-center justify-between">
      <div>
        <h2 class="font-semibold">投研上下文</h2>
        <p class="text-xs text-muted-foreground">自选、预测与最新信号</p>
      </div>
      <Button variant="ghost" size="icon" :disabled="loading" aria-label="刷新上下文" @click="load">
        <RefreshCw class="size-4" :class="loading ? 'animate-spin' : ''" aria-hidden="true" />
      </Button>
    </div>

    <section aria-labelledby="context-watchlist" class="border-t py-4">
      <div class="mb-2 flex items-center gap-2">
        <Star class="size-4 text-primary" aria-hidden="true" />
        <h3 id="context-watchlist" class="text-sm font-semibold">自选摘要</h3>
      </div>
      <ErrorState v-if="errors.quotes && quotes.length === 0" compact :message="errors.quotes.friendly" @retry="load" />
      <ul v-else-if="quotes.length" class="space-y-1">
        <li v-for="quote in quotes" :key="quote.code">
          <RouterLink
            :to="`/detail/${quote.code}`"
            class="flex min-h-11 items-center justify-between rounded-md px-2 py-1.5 text-sm hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
          >
            <span class="min-w-0">
              <span class="block truncate font-medium">{{ quote.name }}</span>
              <span class="font-mono text-[11px] text-muted-foreground">{{ quote.code }}</span>
            </span>
            <span class="text-right font-mono text-xs">
              <span class="block">{{ fmtPrice(quote.price) }}</span>
              <span :class="Number(quote.change_pct) >= 0 ? 'text-up' : 'text-down'">{{ fmtPct(quote.change_pct) }}</span>
            </span>
          </RouterLink>
        </li>
      </ul>
      <p v-else-if="!loading" class="py-3 text-center text-xs text-muted-foreground">暂无自选报价</p>
    </section>

    <section aria-labelledby="context-predictions" class="border-t py-4">
      <div class="mb-2 flex items-center gap-2">
        <Target class="size-4 text-primary" aria-hidden="true" />
        <h3 id="context-predictions" class="text-sm font-semibold">近期预测</h3>
        <RouterLink to="/predictions" class="ml-auto text-xs text-primary hover:underline">全部</RouterLink>
      </div>
      <ErrorState v-if="errors.predictions && predictions.length === 0" compact :message="errors.predictions.friendly" @retry="load" />
      <ul v-else-if="predictions.length" class="space-y-2">
        <li v-for="prediction in predictions" :key="prediction.id" class="rounded-md bg-muted/50 p-2 text-xs">
          <div class="flex items-center gap-2">
            <RouterLink v-if="prediction.code" :to="`/detail/${prediction.code}`" class="font-mono font-semibold hover:text-primary">
              {{ prediction.name || prediction.code }}
            </RouterLink>
            <span v-else class="font-semibold">市场判断</span>
            <Badge variant="secondary" class="ml-auto text-[10px]">{{ predictionLabels[prediction.status] || prediction.status }}</Badge>
          </div>
          <p class="mt-1 line-clamp-2 text-muted-foreground">{{ prediction.prediction }}</p>
        </li>
      </ul>
      <p v-else-if="!loading" class="py-3 text-center text-xs text-muted-foreground">还没有预测记录</p>
    </section>

    <section aria-labelledby="context-signals" class="border-t py-4">
      <div class="mb-2 flex items-center gap-2">
        <Bell class="size-4 text-primary" aria-hidden="true" />
        <h3 id="context-signals" class="text-sm font-semibold">最新信号</h3>
        <RouterLink to="/signals" class="ml-auto text-xs text-primary hover:underline">全部</RouterLink>
      </div>
      <ErrorState v-if="errors.signals && signals.length === 0" compact :message="errors.signals.friendly" @retry="load" />
      <ul v-else-if="signals.length" class="space-y-2">
        <li v-for="signal in signals" :key="`${signal.timestamp}-${signal.rule_id}-${signal.code}`" class="rounded-md bg-muted/50 p-2 text-xs">
          <div class="flex items-center gap-2">
            <RouterLink :to="`/detail/${signal.code}`" class="font-medium hover:text-primary">{{ signal.name || signal.code }}</RouterLink>
            <Badge :variant="signal.severity === 'critical' ? 'destructive' : 'secondary'" class="ml-auto text-[10px]">
              {{ severityLabels[signal.severity] }}
            </Badge>
          </div>
          <p class="mt-1 line-clamp-2 text-muted-foreground">{{ signal.title }}</p>
        </li>
      </ul>
      <p v-else-if="!loading" class="py-3 text-center text-xs text-muted-foreground">当前没有新信号</p>
    </section>
  </aside>
</template>
