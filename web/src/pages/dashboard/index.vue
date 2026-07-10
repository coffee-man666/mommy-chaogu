<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { apiGet } from '@/api/client'
import { fmtPrice, fmtPct, fmtWan } from '@/utils/format'
import { cn } from '@/lib/utils'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import type { IndexQuote, SectorQuote, Signal, Quote, PortfolioSummary } from '@/api/types'

interface SnapshotResponse {
  quotes: Quote[]
  timestamp: string
}

const router = useRouter()

// ---------- 数据 ----------
const indexes = ref<IndexQuote[]>([])
const quotes = ref<Quote[]>([])
const portfolio = ref<PortfolioSummary | null>(null)
const sectors = ref<SectorQuote[]>([])
const recentSignals = ref<Signal[]>([])
const watchCodes = ref<string[]>([])
const dataAge = ref(0)
const loading = ref(false)

let refreshTimer: number | null = null
let ageTimer: number | null = null

async function loadWatchlist() {
  try {
    type WatchlistStock = { code: string; name: string; group: string }
    const list = await apiGet<WatchlistStock[]>('/api/watchlist')
    watchCodes.value = list.map((s) => s.code)
  } catch {
    watchCodes.value = []
  }
}

async function loadAll() {
  loading.value = true
  // 先拿到自选股代码，再拉行情（保证 quote 覆盖自选股）
  if (watchCodes.value.length === 0) await loadWatchlist()
  await Promise.all([
    apiGet<IndexQuote[]>('/api/market/indexes')
      .then((d) => (indexes.value = d))
      .catch(() => {}),
    apiGet<SnapshotResponse>('/api/quotes')
      .then((d) => (quotes.value = d.quotes ?? []))
      .catch(() => {}),
    apiGet<PortfolioSummary>('/api/portfolio')
      .then((d) => (portfolio.value = d))
      .catch(() => {}),
    apiGet<Signal[]>('/api/signals/recent')
      .then((d) => (recentSignals.value = d.slice(0, 5)))
      .catch(() => {}),
    apiGet<SectorQuote[]>('/api/market/sectors?limit=12')
      .then((d) => (sectors.value = d))
      .catch(() => {}),
  ])
  dataAge.value = 0
  loading.value = false
}

onMounted(() => {
  loadAll()
  refreshTimer = window.setInterval(loadAll, 30_000)
  ageTimer = window.setInterval(() => dataAge.value++, 1000)
})

onUnmounted(() => {
  if (refreshTimer) clearInterval(refreshTimer)
  if (ageTimer) clearInterval(ageTimer)
})

// ---------- 派生 ----------
const dataDescription = computed(() => {
  if (dataAge.value < 30) return '实时'
  if (dataAge.value < 120) return `${dataAge.value}秒前`
  return `${Math.floor(dataAge.value / 60)}分钟前`
})

/** 自选股行情（仅展示有报价的，最多 8 条） */
const watchlistQuotes = computed(() => {
  const set = new Set(watchCodes.value)
  return quotes.value
    .filter((q) => set.has(q.code))
    .slice(0, 8)
})

/** 按涨跌幅排序的板块（前 8） */
const sortedSectors = computed(() =>
  [...sectors.value]
    .sort((a, b) => Number(b.change_pct) - Number(a.change_pct))
    .slice(0, 8),
)

/** 涨跌颜色 class */
function changeClass(v: string | number | null | undefined): string {
  if (v == null) return 'text-muted-foreground'
  const n = Number(v)
  if (isNaN(n) || n === 0) return 'text-muted-foreground'
  return n > 0 ? 'text-up' : 'text-down'
}

// AI 快速入口
const aiQuickActions = [
  { label: '今天怎么样？', prompt: '今天大盘怎么样' },
  { label: '持仓分析', prompt: '帮我分析一下持仓' },
  { label: '主力在买什么？', prompt: '今天主力资金在买哪些板块' },
  { label: '自选股异动', prompt: '我的自选股今天有什么异动' },
]

function goAgent(prompt?: string) {
  router.push({ name: 'agent', query: prompt ? { q: prompt } : undefined })
}

function goDetail(code: string) {
  router.push({ name: 'detail', params: { code } })
}

const severityDot: Record<Signal['severity'], string> = {
  critical: 'bg-destructive',
  warning: 'bg-yellow-500',
  info: 'bg-blue-500',
}
</script>

<template>
  <div class="mx-auto w-full max-w-7xl space-y-4 p-4 lg:p-6">
    <!-- 页面标题 + 数据年龄 -->
    <div class="flex items-center justify-between">
      <h1 class="text-xl font-bold tracking-tight">📊 仪表盘</h1>
      <div class="flex items-center gap-2 text-xs text-muted-foreground">
        <span
          class="inline-block size-2 rounded-full"
          :class="loading ? 'animate-pulse bg-yellow-500' : 'bg-up'"
        />
        {{ dataDescription }}
      </div>
    </div>

    <!-- 指数卡片行 -->
    <div class="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
      <Card
        v-for="idx in indexes.slice(0, 6)"
        :key="idx.code"
        class="gap-0 py-4"
      >
        <CardContent class="px-4">
          <p class="truncate text-xs text-muted-foreground">{{ idx.name }}</p>
          <p class="mt-1 font-mono text-lg font-bold tabular-nums">
            {{ fmtPrice(idx.price) }}
          </p>
          <p
            class="mt-0.5 font-mono text-sm font-semibold tabular-nums"
            :class="changeClass(idx.change_pct)"
          >
            {{ fmtPct(idx.change_pct) }}
          </p>
        </CardContent>
      </Card>
      <Card v-if="indexes.length === 0" class="col-span-full py-6">
        <CardContent class="px-4 text-center text-sm text-muted-foreground">
          指数数据加载中…
        </CardContent>
      </Card>
    </div>

    <!-- 主区域：左列(自选股) + 右列(持仓/AI/板块/信号) -->
    <div class="grid grid-cols-1 gap-4 lg:grid-cols-3">
      <!-- 自选股快览 -->
      <Card class="lg:col-span-2">
        <CardHeader class="flex items-center justify-between">
          <CardTitle class="text-base">📋 自选股快览</CardTitle>
          <Button variant="ghost" size="sm" @click="router.push({ name: 'market' })">
            全部 →
          </Button>
        </CardHeader>
        <Separator />
        <CardContent class="px-0">
          <Table v-if="watchlistQuotes.length > 0">
            <TableHeader>
              <TableRow>
                <TableHead class="pl-6">代码</TableHead>
                <TableHead>名称</TableHead>
                <TableHead class="text-right">现价</TableHead>
                <TableHead class="text-right">涨跌幅</TableHead>
                <TableHead class="pr-6 text-right">主力净流入</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              <TableRow
                v-for="q in watchlistQuotes"
                :key="q.code"
                class="cursor-pointer"
                @click="goDetail(q.code)"
              >
                <TableCell class="pl-6 font-mono text-xs text-muted-foreground">
                  {{ q.code }}
                </TableCell>
                <TableCell class="font-medium">{{ q.name }}</TableCell>
                <TableCell class="text-right font-mono tabular-nums">
                  {{ fmtPrice(q.price) }}
                </TableCell>
                <TableCell
                  class="text-right font-mono font-semibold tabular-nums"
                  :class="changeClass(q.change_pct)"
                >
                  {{ fmtPct(q.change_pct) }}
                </TableCell>
                <TableCell
                  class="pr-6 text-right font-mono text-xs tabular-nums"
                  :class="changeClass(q.main_net_inflow)"
                >
                  {{ fmtWan(q.main_net_inflow) }}
                </TableCell>
              </TableRow>
            </TableBody>
          </Table>
          <div
            v-else
            class="flex flex-col items-center gap-2 py-10 text-sm text-muted-foreground"
          >
            <span>暂无自选股行情</span>
            <Button variant="outline" size="sm" @click="router.push({ name: 'settings' })">
              去添加自选股
            </Button>
          </div>
        </CardContent>
      </Card>

      <!-- 持仓总览 -->
      <Card>
        <CardHeader class="flex items-center justify-between">
          <CardTitle class="text-base">💰 持仓总览</CardTitle>
          <Button variant="ghost" size="sm" @click="router.push({ name: 'portfolio' })">
            详情 →
          </Button>
        </CardHeader>
        <Separator />
        <CardContent class="pt-4">
          <template v-if="portfolio && portfolio.n_positions > 0">
            <div class="space-y-3">
              <div>
                <p class="text-xs text-muted-foreground">总市值</p>
                <p class="font-mono text-2xl font-bold tabular-nums">
                  {{ fmtWan(portfolio.total_market_value) }}
                </p>
              </div>
              <Separator />
              <div class="grid grid-cols-2 gap-3">
                <div>
                  <p class="text-xs text-muted-foreground">浮动盈亏</p>
                  <p
                    class="font-mono text-lg font-bold tabular-nums"
                    :class="changeClass(portfolio.total_unrealized_pnl)"
                  >
                    {{ Number(portfolio.total_unrealized_pnl ?? 0) >= 0 ? '+' : ''
                    }}{{ fmtWan(portfolio.total_unrealized_pnl) }}
                  </p>
                </div>
                <div>
                  <p class="text-xs text-muted-foreground">盈亏率</p>
                  <p
                    class="font-mono text-lg font-bold tabular-nums"
                    :class="changeClass(portfolio.total_unrealized_pnl_pct)"
                  >
                    {{ fmtPct(portfolio.total_unrealized_pnl_pct) }}
                  </p>
                </div>
              </div>
              <Separator />
              <div class="flex items-center justify-between text-xs text-muted-foreground">
                <span>持仓数</span>
                <span class="font-mono">{{ portfolio.n_positions }}</span>
              </div>
            </div>
          </template>
          <div
            v-else
            class="flex flex-col items-center gap-2 py-8 text-sm text-muted-foreground"
          >
            <span>暂无持仓</span>
            <Button variant="outline" size="sm" @click="router.push({ name: 'portfolio' })">
              录入持仓
            </Button>
          </div>
        </CardContent>
      </Card>

      <!-- AI 快速入口 -->
      <Card>
        <CardHeader>
          <CardTitle class="text-base">🤖 AI 快速入口</CardTitle>
          <CardDescription>一句话问 AI 助手</CardDescription>
        </CardHeader>
        <Separator />
        <CardContent class="grid grid-cols-2 gap-2 pt-4">
          <Button
            v-for="action in aiQuickActions"
            :key="action.label"
            variant="outline"
            size="sm"
            class="justify-start"
            @click="goAgent(action.prompt)"
          >
            {{ action.label }}
          </Button>
          <Button class="col-span-2" size="sm" @click="goAgent()">
            打开 AI 对话 →
          </Button>
        </CardContent>
      </Card>

      <!-- 板块排行（badge 列表） -->
      <Card class="lg:col-span-2">
        <CardHeader class="flex items-center justify-between">
          <CardTitle class="text-base">🔥 板块排行</CardTitle>
          <span class="text-xs text-muted-foreground">按涨跌幅</span>
        </CardHeader>
        <Separator />
        <CardContent class="flex flex-wrap gap-2 pt-4">
          <template v-if="sortedSectors.length > 0">
            <Badge
              v-for="(s, i) in sortedSectors"
              :key="s.code"
              variant="outline"
              :class="
                cn(
                  'gap-1.5 py-1.5 text-sm tabular-nums',
                  changeClass(s.change_pct),
                )
              "
            >
              <span class="text-xs text-muted-foreground">{{ i + 1 }}</span>
              <span class="font-medium">{{ s.name }}</span>
              <span class="font-mono">{{ fmtPct(s.change_pct) }}</span>
            </Badge>
          </template>
          <span v-else class="py-4 text-sm text-muted-foreground">暂无板块数据</span>
        </CardContent>
      </Card>

      <!-- 最近信号 -->
      <Card>
        <CardHeader class="flex items-center justify-between">
          <CardTitle class="text-base">🔔 最近信号</CardTitle>
          <Button variant="ghost" size="sm" @click="router.push({ name: 'signals' })">
            全部 →
          </Button>
        </CardHeader>
        <Separator />
        <CardContent class="space-y-3 pt-4">
          <template v-if="recentSignals.length > 0">
            <div
              v-for="sig in recentSignals"
              :key="sig.timestamp + sig.code"
              class="flex items-start gap-2"
            >
              <span
                class="mt-1.5 size-2 shrink-0 rounded-full"
                :class="severityDot[sig.severity]"
              />
              <div class="min-w-0 flex-1">
                <p class="truncate text-sm font-medium">{{ sig.title }}</p>
                <p class="truncate text-xs text-muted-foreground">
                  <span v-if="sig.name">{{ sig.name }} · </span>{{ sig.detail }}
                </p>
              </div>
            </div>
          </template>
          <p v-else class="py-4 text-center text-sm text-muted-foreground">暂无信号</p>
        </CardContent>
      </Card>
    </div>
  </div>
</template>
