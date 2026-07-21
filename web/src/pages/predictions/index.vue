<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { getPredictions, getPredictionStats } from '@/api/predictions'
import { fmtPrice } from '@/utils/format'
import { cn } from '@/lib/utils'
import type { Prediction, PredictionStats, PredictionStatus } from '@/api/types'

import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'

const router = useRouter()

const predictions = ref<Prediction[]>([])
const stats = ref<PredictionStats | null>(null)
const loading = ref(true)
const error = ref(false)

async function load() {
  const [listRes, statsRes] = await Promise.allSettled([
    getPredictions(20),
    getPredictionStats(),
  ])
  if (listRes.status === 'fulfilled') {
    predictions.value = listRes.value
  } else {
    error.value = true
  }
  if (statsRes.status === 'fulfilled') {
    stats.value = statsRes.value
  }
  loading.value = false
}

// ---------- 方向徽章 ----------
// 故意不用涨跌色（红/绿），用蓝/橙避免和 A 股配色混淆。
const directionConfig: Record<string, { label: string; cls: string }> = {
  up: { label: '看多', cls: 'bg-blue-500/15 text-blue-600 dark:text-blue-400' },
  down: { label: '看空', cls: 'bg-orange-500/15 text-orange-600 dark:text-orange-400' },
}

function directionOf(d: string): { label: string; cls: string } {
  return directionConfig[d] ?? { label: d || '中性', cls: 'bg-secondary text-secondary-foreground' }
}

// ---------- status 徽章 ----------
const statusConfig: Record<
  PredictionStatus,
  { label: string; variant: 'default' | 'secondary' | 'destructive' | 'outline'; cls?: string }
> = {
  pending: { label: '待验证', variant: 'secondary' },
  // 命中用「成功」语义的绿，不用涨跌色变量
  hit: { label: '命中', variant: 'secondary', cls: 'bg-green-500/15 text-green-600 dark:text-green-400' },
  missed: { label: '未中', variant: 'destructive' },
  expired: { label: '已过期', variant: 'outline' },
  unverifiable: { label: '无法验证', variant: 'outline' },
}

function statusOf(s: PredictionStatus) {
  return statusConfig[s] ?? { label: s, variant: 'secondary' as const }
}

// ---------- 时间格式化 ----------
function fmtCountdown(iso: string): string {
  const d = new Date(iso)
  if (isNaN(d.getTime())) return '-'
  const diff = d.getTime() - Date.now()
  if (diff <= 0) return '已到期'
  const days = Math.floor(diff / 86_400_000)
  const hours = Math.floor((diff % 86_400_000) / 3_600_000)
  if (days >= 1) return `${days}天后`
  if (hours >= 1) return `${hours}小时后`
  const mins = Math.floor((diff % 3_600_000) / 60_000)
  return `${mins}分钟后`
}

function fmtDate(iso: string): string {
  const d = new Date(iso)
  if (isNaN(d.getTime())) return iso
  return d.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
}

// 已验证预测的实际价 vs 入场价偏差
function deviation(p: Prediction): { text: string; positive: boolean } | null {
  if (p.actual_price == null || p.entry_price == null || p.entry_price === 0) return null
  const pct = ((p.actual_price - p.entry_price) / p.entry_price) * 100
  const sign = pct >= 0 ? '+' : ''
  return { text: `${sign}${pct.toFixed(2)}%`, positive: pct >= 0 }
}

const hitRatePct = computed(() =>
  stats.value ? `${Math.round(stats.value.hit_rate * 100)}%` : '-',
)

// 预计算每条已验证预测的偏差（避免模板里重复调用 + 字符串解析）
const deviationById = computed(() => {
  const m = new Map<number, { text: string; positive: boolean }>()
  for (const p of predictions.value) {
    const d = deviation(p)
    if (d) m.set(p.id, d)
  }
  return m
})

function isStockCode(code: string): boolean {
  return /^\d{6}$/.test(code)
}

function goDetail(code: string) {
  if (isStockCode(code)) router.push({ name: 'detail', params: { code } })
}

onMounted(load)
</script>

<template>
  <div class="mx-auto w-full max-w-4xl space-y-4 p-4 lg:p-6">
    <!-- 页头 -->
    <div class="flex items-center justify-between">
      <h1 class="text-xl font-bold tracking-tight">🎯 预测跟踪</h1>
      <span class="font-mono text-xs text-muted-foreground">命中率闭环</span>
    </div>

    <!-- 顶部统计条 -->
    <div class="grid grid-cols-2 gap-3 lg:grid-cols-5">
      <template v-if="loading && !stats">
        <Card v-for="i in 5" :key="i">
          <CardContent class="space-y-2">
            <Skeleton class="h-3 w-14" />
            <Skeleton class="h-7 w-16" />
          </CardContent>
        </Card>
      </template>
      <template v-else>
        <Card>
          <CardContent class="space-y-1">
            <p class="text-xs text-muted-foreground">总数</p>
            <p class="font-mono text-2xl font-bold tabular-nums">{{ stats?.total ?? 0 }}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent class="space-y-1">
            <p class="text-xs text-muted-foreground">待验证</p>
            <p class="font-mono text-2xl font-bold tabular-nums text-muted-foreground">
              {{ stats?.pending ?? 0 }}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent class="space-y-1">
            <p class="text-xs text-muted-foreground">命中</p>
            <p class="font-mono text-2xl font-bold tabular-nums text-green-600 dark:text-green-400">
              {{ stats?.hit ?? 0 }}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent class="space-y-1">
            <p class="text-xs text-muted-foreground">未中</p>
            <p class="font-mono text-2xl font-bold tabular-nums text-destructive">
              {{ stats?.missed ?? 0 }}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent class="space-y-1">
            <p class="text-xs text-muted-foreground">命中率</p>
            <p class="font-mono text-2xl font-bold tabular-nums">{{ hitRatePct }}</p>
          </CardContent>
        </Card>
      </template>
    </div>

    <!-- 预测卡片列表 -->
    <div class="space-y-3">
      <!-- 加载骨架 -->
      <template v-if="loading">
        <Card v-for="i in 3" :key="i">
          <CardContent class="space-y-3">
            <div class="flex items-center gap-2">
              <Skeleton class="h-5 w-12" />
              <Skeleton class="h-5 w-32" />
              <Skeleton class="h-5 w-16" />
            </div>
            <Skeleton class="h-4 w-3/4" />
            <div class="flex gap-4">
              <Skeleton class="h-8 w-20" />
              <Skeleton class="h-8 w-20" />
              <Skeleton class="h-8 w-20" />
            </div>
          </CardContent>
        </Card>
      </template>

      <!-- 错误空态 -->
      <Card v-else-if="error && predictions.length === 0">
        <CardContent class="flex flex-col items-center gap-2 py-16 text-center">
          <span class="text-5xl">⚠️</span>
          <p class="text-base font-semibold text-destructive">数据加载失败</p>
          <p class="text-sm text-muted-foreground">预测服务暂时不可用，请稍后重试</p>
        </CardContent>
      </Card>

      <!-- 真空态 -->
      <Card v-else-if="predictions.length === 0">
        <CardContent class="flex flex-col items-center gap-2 py-16 text-center">
          <span class="text-5xl">🔮</span>
          <p class="text-base font-semibold text-muted-foreground">还没有预测记录</p>
          <p class="text-sm text-muted-foreground">让 AI 对个股做出预测后会出现在这里</p>
        </CardContent>
      </Card>

      <!-- 预测卡片 -->
      <template v-else>
        <Card
          v-for="p in predictions"
          :key="p.id"
          :class="[
            'border-l-4',
            isStockCode(p.code)
              ? 'cursor-pointer border-l-primary/60 transition-transform hover:shadow-md active:scale-[0.99]'
              : 'border-l-primary/60',
          ]"
          :role="isStockCode(p.code) ? 'link' : undefined"
          :tabindex="isStockCode(p.code) ? 0 : undefined"
          @click="goDetail(p.code)"
          @keydown.enter="goDetail(p.code)"
          @keydown.space.prevent="goDetail(p.code)"
        >
          <CardContent class="space-y-3">
            <!-- 头部：方向 + 名称/代码 + 状态 + 倒计时 -->
            <div class="flex flex-wrap items-center gap-2">
              <Badge
                :class="cn('text-xs font-semibold', directionOf(p.direction).cls)"
              >
                {{ directionOf(p.direction).label }}
              </Badge>
              <span class="flex-1 truncate font-semibold text-card-foreground">
                <span>{{ p.name || p.code }}</span>
                <span class="ml-1 font-mono text-xs text-muted-foreground">{{ p.code }}</span>
              </span>
              <Badge
                :variant="statusOf(p.status).variant"
                :class="cn('text-xs', statusOf(p.status).cls)"
              >
                {{ statusOf(p.status).label }}
              </Badge>
            </div>

            <!-- 预测文本 + 依据 -->
            <div class="space-y-1">
              <p class="text-sm font-medium leading-snug text-card-foreground">
                {{ p.prediction }}
                <span class="ml-1 text-xs text-muted-foreground">· {{ p.timeframe }}</span>
              </p>
              <p v-if="p.rationale" class="text-xs leading-relaxed text-muted-foreground line-clamp-2">
                {{ p.rationale }}
              </p>
            </div>

            <!-- 三档价位 -->
            <div class="grid grid-cols-3 gap-2 text-sm">
              <div class="rounded-md bg-muted/40 px-2 py-1.5">
                <p class="text-[10px] text-muted-foreground">目标价</p>
                <p class="font-mono font-semibold tabular-nums">{{ fmtPrice(p.target_price) }}</p>
              </div>
              <div class="rounded-md bg-muted/40 px-2 py-1.5">
                <p class="text-[10px] text-muted-foreground">入场价</p>
                <p class="font-mono font-semibold tabular-nums">{{ fmtPrice(p.entry_price) }}</p>
              </div>
              <div class="rounded-md bg-muted/40 px-2 py-1.5">
                <p class="text-[10px] text-muted-foreground">止损价</p>
                <p class="font-mono font-semibold tabular-nums">{{ fmtPrice(p.stop_loss) }}</p>
              </div>
            </div>

            <!-- 底部：时间 + 倒计时 / 验证结果 -->
            <div class="flex flex-wrap items-center justify-between gap-2 border-t pt-2 text-xs text-muted-foreground">
              <span class="font-mono">📅 {{ fmtDate(p.created_at) }}</span>
              <template v-if="p.status === 'pending'">
                <span class="font-mono">⏳ {{ fmtCountdown(p.verify_after) }} 验证</span>
              </template>
              <template v-else-if="p.actual_price != null">
                <span class="flex items-center gap-2 font-mono">
                  <span>实际 {{ fmtPrice(p.actual_price) }}</span>
                  <span
                    v-if="deviationById.get(p.id)"
                    :class="deviationById.get(p.id)!.positive
                      ? 'text-green-600 dark:text-green-400'
                      : 'text-destructive'"
                  >
                    {{ deviationById.get(p.id)!.text }}
                  </span>
                </span>
              </template>
              <span v-else class="font-mono">{{ statusOf(p.status).label }}</span>
            </div>
          </CardContent>
        </Card>
      </template>
    </div>
  </div>
</template>
