<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed, nextTick, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { apiGet, toApiError, type ApiError } from '@/api/client'
import { fmtPrice, fmtPct, fmtWan, fmtMoney, fmtAge } from '@/utils/format'
import type { Quote, Bar, MoneyFlowResponse } from '@/api/types'
import type { Prediction, StockDecisionContext } from '@/api/types'
import { getStockPredictions } from '@/api/predictions'
import { getStockDecisionContext } from '@/api/market'
import { getStockBacktest, type BacktestResult } from '@/api/backtest'
import { getPreferences } from '@/api/preferences'
import { coverageBadgeLabels, fmtCountdown, verifyFreshnessText } from '@/lib/predictionEvidence'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import {
  Table,
  TableBody,
  TableRow,
  TableCell,
} from '@/components/ui/table'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import ErrorState from '@/components/ErrorState.vue'
import { cn } from '@/lib/utils'
import { useWatchlistStore } from '@/stores/watchlist'

const props = defineProps<{ code: string }>()
const route = useRoute()
const router = useRouter()
const watchlistStore = useWatchlistStore()

// ---------- 状态 ----------
const quote = ref<Quote | null>(null)
const quoteLoading = ref(true)
/** 报价拉取失败原因（成功时清空；有旧报价时继续展示旧报价） */
const quoteError = ref<ApiError | null>(null)
const bars = ref<Bar[]>([])
const klineChart = ref<any>(null)
const interval = ref<string>('1d')

const flowToday = ref<MoneyFlowResponse | null>(null)
const flowHistory = ref<MoneyFlowResponse | null>(null)
const flowTab = ref<string>('today')
const flowDays = ref(30)
const flowLoading = ref(false)

// 主 Tab：概览 / 走势 / 资金 / 决策记录
const MAIN_TABS = ['overview', 'chart', 'flow', 'decisions'] as const
type MainTab = (typeof MAIN_TABS)[number]
const requestedTab = typeof route.query.tab === 'string' ? route.query.tab : 'overview'
const mainTab = ref<MainTab>(
  MAIN_TABS.includes(requestedTab as MainTab) ? (requestedTab as MainTab) : 'overview'
)

// 预测记录（决策记录 Tab）
const stockPredictions = ref<Prediction[]>([])
const predictionsLoading = ref(false)

// 回测面板（决策记录 Tab 顶部）
const defaultHoldDays = ref<number | null>(null)
const backtest = ref<BacktestResult | null>(null)
const backtestLoading = ref(false)
const backtestError = ref<string | null>(null)

const codeInput = ref('')
const actionMessage = ref('')
const decisionContext = ref<StockDecisionContext | null>(null)

let refreshTimer: number | null = null
let themeObserver: MutationObserver | null = null

const isWatched = computed(() => watchlistStore.allCodes.includes(props.code))
const sourceBasket = computed(() => {
  const requested = typeof route.query.basket === 'string' ? route.query.basket : ''
  return decisionContext.value?.baskets.find((basket) => basket.id === requested) ?? null
})
const holdingPnl = computed(() => {
  const holding = decisionContext.value?.holding
  if (!holding || !quote.value) return null
  const marketValue = Number(quote.value.price) * holding.shares
  const pnl = marketValue - Number(holding.total_cost)
  const pct = Number(holding.total_cost) > 0 ? (pnl / Number(holding.total_cost)) * 100 : 0
  return { pnl, pct }
})

const intervals = [
  { key: '5m', label: '5分' },
  { key: '15m', label: '15分' },
  { key: '30m', label: '30分' },
  { key: '60m', label: '60分' },
  { key: '1d', label: '日K' },
  { key: '1w', label: '周K' },
  { key: '1M', label: '月K' },
]

// ---------- 工具函数 ----------

/** 涨跌方向 → Tailwind class（红涨绿跌） */
function dirClass(val: string | number | null | undefined): string {
  if (val == null) return ''
  const n = Number(val)
  if (isNaN(n) || n === 0) return 'text-muted-foreground'
  return n > 0 ? 'text-up' : 'text-down'
}

/** 正值加 + 号 */
function dirSign(val: string | number | null | undefined): string {
  if (val == null) return ''
  return Number(val) >= 0 ? '+' : ''
}

/** 相对昨收的方向 class */
function dirClassRef(val: string | number | null | undefined, ref: string | number | null | undefined): string {
  if (val == null || ref == null) return ''
  const n = Number(val)
  const r = Number(ref)
  if (isNaN(n) || isNaN(r)) return ''
  const diff = n - r
  if (diff === 0) return 'text-muted-foreground'
  return diff > 0 ? 'text-up' : 'text-down'
}

/** 万/亿金额格式化 */
function fmtFlowWan(s: string | null | undefined): string {
  if (!s) return '-'
  const n = Number(s)
  if (isNaN(n)) return String(s)
  return fmtWan(n)
}

// ---------- 数据加载 ----------

async function loadQuote() {
  quoteLoading.value = true
  try {
    quote.value = await apiGet<Quote>(`/api/quotes/${props.code}`)
    quoteError.value = null
  } catch (e) {
    const err = toApiError(e)
    quoteError.value = err
    console.error(err.raw)
  } finally {
    quoteLoading.value = false
  }
}

async function loadDecisionContext() {
  try {
    decisionContext.value = await getStockDecisionContext(props.code)
  } catch {
    decisionContext.value = null
  }
}

/** 报价卡错误文案：404 说明代码可能输错，其余用统一 friendly */
const quoteErrorMessage = computed(() => {
  const e = quoteError.value
  if (!e) return ''
  return e.status === 404 ? '没查到这只股票，请检查代码是否正确' : e.friendly
})

async function loadBars() {
  try {
    const isDayOrAbove = interval.value === '1d' || interval.value === '1w' || interval.value === '1M'
    const limit = isDayOrAbove ? 250 : 200
    bars.value = await apiGet<Bar[]>(
      `/api/quotes/${props.code}/bars?interval=${interval.value}&limit=${limit}&adjustment=forward`
    )
    await nextTick()
    drawKLine()
  } catch (e) {
    console.error(e)
  }
}

async function loadFlow() {
  flowLoading.value = true
  try {
    const [today, hist] = await Promise.all([
      apiGet<MoneyFlowResponse>(`/api/quotes/${props.code}/money_flow/today`).catch(() => null),
      apiGet<MoneyFlowResponse>(
        `/api/quotes/${props.code}/money_flow/history?days=${flowDays.value}`
      ).catch(() => null),
    ])
    if (today) flowToday.value = today
    if (hist) flowHistory.value = hist
  } finally {
    flowLoading.value = false
  }
}

async function loadPredictions() {
  predictionsLoading.value = true
  try {
    stockPredictions.value = await getStockPredictions(props.code)
  } catch {
    stockPredictions.value = []
  } finally {
    predictionsLoading.value = false
  }
}

/** 用户偏好只用于展示默认持有天数，失败静默（不影响预测列表） */
async function loadPreferences() {
  try {
    const prefs = await getPreferences()
    defaultHoldDays.value = prefs.default_hold_days
  } catch {
    defaultHoldDays.value = null
  }
}

const backtestSubtitle = computed(() =>
  defaultHoldDays.value != null
    ? `默认持有 ${defaultHoldDays.value} 天（可在「我的」修改）`
    : '持有天数使用服务端默认值（可在「我的」修改）'
)

async function runBacktest() {
  backtestLoading.value = true
  backtestError.value = null
  try {
    backtest.value = await getStockBacktest(props.code)
  } catch (e) {
    backtestError.value = toApiError(e, '回测').friendly
  } finally {
    backtestLoading.value = false
  }
}

// ---------- 回测指标格式化（null → 破折号） ----------

function fmtWinRate(v: number | null): string {
  return v == null ? '—' : `${(v * 100).toFixed(1)}%`
}

function fmtReturnPct(v: number | null): string {
  return v == null ? '—' : `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`
}

function fmtDrawdownPct(v: number | null): string {
  return v == null ? '—' : `${v.toFixed(2)}%`
}

function fmtSharpe(v: number | null): string {
  return v == null ? '—' : v.toFixed(2)
}

/** pending 预测的验证截止文案：倒计时，已到期/无效则展示原始时间 */
function pendingVerifyText(p: Prediction): string {
  const countdown = fmtCountdown(p.verify_after)
  return countdown === '已到期' || countdown === '-'
    ? `验证截止 ${p.verify_after}`
    : `⏳ ${countdown} 验证`
}

/** 预测状态 → 中文标签 + 颜色 */
function predictionStatusBadge(status: string): { label: string; class: string } {
  const map: Record<string, { label: string; class: string }> = {
    pending: { label: '待验证', class: 'bg-blue-100 text-blue-700' },
    hit: { label: '已命中', class: 'bg-green-100 text-green-700' },
    missed: { label: '未命中', class: 'bg-red-100 text-red-700' },
    expired: { label: '已过期', class: 'bg-gray-100 text-gray-500' },
    unverifiable: { label: '无法验证', class: 'bg-orange-100 text-orange-700' },
  }
  return map[status] || { label: status, class: 'bg-gray-100 text-gray-500' }
}

async function changeFlowDays(d: number) {
  flowDays.value = d
  try {
    flowHistory.value = await apiGet<MoneyFlowResponse>(
      `/api/quotes/${props.code}/money_flow/history?days=${d}`
    )
  } catch (e) {
    console.error(e)
  }
}

// ---------- K 线 ----------

async function drawKLine() {
  try {
    const isFirstInit = !klineChart.value
    if (isFirstInit) {
      const klinecharts = await import('klinecharts')
      const el = document.getElementById('kline') as HTMLElement
      if (!el) return
      klineChart.value = klinecharts.init(el)
    }
    const chart = klineChart.value

    const rootStyles = getComputedStyle(document.documentElement)
    const cssColor = (name: string, fallback: string) => {
      const value = rootStyles.getPropertyValue(name).trim()
      return value ? `hsl(${value})` : fallback
    }

    chart.setStyles({
      grid: {
        show: true,
        horizontal: { show: true, color: cssColor('--border', '#e5e7eb') },
        vertical: { show: true, color: cssColor('--border', '#e5e7eb') },
      },
      candle: {
        bar: {
          upColor: 'var(--color-up)',
          downColor: 'var(--color-down)',
          noChangeColor: cssColor('--muted-foreground', '#737373'),
        },
      },
      indicator: {
        tooltip: { text: { color: cssColor('--foreground', '#171717') } },
      },
    })

    if (isFirstInit) {
      chart.createIndicator('MA', false, { id: 'candle_pane' })
      chart.createIndicator('VOL')
    }

    const dataList = bars.value.map((b) => ({
      timestamp: new Date(b.timestamp).getTime(),
      open: Number(b.open),
      high: Number(b.high),
      low: Number(b.low),
      close: Number(b.close),
      volume: Number(b.volume),
    }))
    chart.applyNewData(dataList)
  } catch (e) {
    console.error('drawKLine failed', e)
  }
}

function changeInterval(key: string) {
  interval.value = key
  loadBars()
}

// ---------- 回车跳转 ----------

function onCodeEnter() {
  const c = codeInput.value.trim()
  if (!c) return
  router.push({ name: 'detail', params: { code: c }, query: { tab: mainTab.value } })
}

function goBack() {
  router.back()
}

async function addToWatchlist() {
  if (isWatched.value) return
  actionMessage.value = ''
  try {
    if (watchlistStore.groups.length === 0) {
      await watchlistStore.addGroup('默认', '从个股详情添加')
    }
    const group = watchlistStore.groups[0]?.name || '默认'
    await watchlistStore.addStock(props.code, group)
    actionMessage.value = `已加入「${group}」`
  } catch (error) {
    actionMessage.value = error instanceof Error ? error.message : '添加失败，请重试'
  }
}

function askAgent() {
  const stockName = quote.value?.name || props.code
  void router.push({
    path: '/chat',
    query: {
      q: '结合我当前看的信息，这只股票现在最需要关注什么？',
      stock: props.code,
      stock_name: stockName,
      tab: mainTab.value,
      basket: sourceBasket.value?.id,
      as_of: quote.value?.timestamp,
    },
  })
}

// ---------- SVG 资金流图 ----------

const SVG_W = 360
const SVG_H_TODAY = 160
const SVG_H_HISTORY = 200
const PAD_L = 4
const PAD_R = 4
const PAD_T = 10
const PAD_B = 20

const todayFlowPoints = computed(() => {
  const items = flowToday.value?.items
  if (!items?.length) return ''
  const W = SVG_W - PAD_L - PAD_R
  const H = SVG_H_TODAY - PAD_T - PAD_B
  const vals = items.map((i) => Number(i.main_net) || 0)
  const maxAbs = Math.max(...vals.map(Math.abs), 1)
  const n = items.length
  const stepX = W / Math.max(n - 1, 1)
  return items
    .map((item, i) => {
      const val = Number(item.main_net) || 0
      const x = PAD_L + i * stepX
      const y = PAD_T + H / 2 - (val / maxAbs) * (H / 2 - 4)
      return `${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')
})

const todayFlowArea = computed(() => {
  const items = flowToday.value?.items
  if (!items?.length) return ''
  const pts = todayFlowPoints.value
  if (!pts) return ''
  const W = SVG_W - PAD_L - PAD_R
  const stepX = W / Math.max(items.length - 1, 1)
  const lastX = PAD_L + (items.length - 1) * stepX
  const midY = PAD_T + (SVG_H_TODAY - PAD_T - PAD_B) / 2
  return `${PAD_L},${midY} ${pts} ${lastX},${midY}`
})

const todayTimeLabels = computed(() => {
  const items = flowToday.value?.items
  if (!items?.length) return []
  return [
    items[0]?.timestamp?.slice(11, 16) || '',
    items[Math.floor(items.length / 2)]?.timestamp?.slice(11, 16) || '',
    items[items.length - 1]?.timestamp?.slice(11, 16) || '',
  ]
})

const historyBars = computed(() => {
  const items = flowHistory.value?.items
  if (!items?.length) return []
  const W = SVG_W - PAD_L - PAD_R
  const H = SVG_H_HISTORY - PAD_T - PAD_B
  const vals = items.map((i) => Number(i.main_net) || 0)
  const maxAbs = Math.max(...vals.map(Math.abs), 1)
  const barW = Math.min(24, (W / items.length) * 0.6)
  const gap = W / items.length
  const midY = PAD_T + H / 2
  return items.map((item, i) => {
    const v = Number(item.main_net) || 0
    const x = PAD_L + i * gap + (gap - barW) / 2
    const barH = (Math.abs(v) / maxAbs) * (H / 2 - 4)
    const y = v >= 0 ? midY - barH : midY
    return {
      x: x.toFixed(1),
      y: y.toFixed(1),
      w: barW.toFixed(1),
      h: barH.toFixed(1),
      color: v >= 0 ? 'var(--color-up)' : 'var(--color-down)',
      date: item.date?.slice(5) || '',
      val: fmtFlowWan(item.main_net),
      labelY: (v >= 0 ? Number(y.toFixed(1)) - 4 : Number(y.toFixed(1)) + Number(barH.toFixed(1)) + 12),
    }
  })
})

const historyMidY = computed(() => PAD_T + (SVG_H_HISTORY - PAD_T - PAD_B) / 2)

/** 当前 Tab 对应的累计数据 */
const activeCumulative = computed(() =>
  flowTab.value === 'today' ? flowToday.value?.cumulative : flowHistory.value?.cumulative
)

// ---------- 懒加载 Tab 数据 ----------

const loadedTabs = ref<Set<string>>(new Set())

function ensureTabLoaded(tab: MainTab) {
  if (loadedTabs.value.has(tab)) return
  loadedTabs.value.add(tab)
  if (tab === 'chart') {
    void loadBars()
  } else if (tab === 'flow') {
    loadFlow()
  } else if (tab === 'decisions') {
    loadPredictions()
    void loadPreferences()
  }
}

watch(mainTab, (tab) => {
  ensureTabLoaded(tab)
  if (route.query.tab !== tab) {
    void router.replace({ query: { ...route.query, tab } })
  }
})

watch(
  () => route.query.tab,
  (tab) => {
    if (typeof tab === 'string' && MAIN_TABS.includes(tab as MainTab)) {
      mainTab.value = tab as MainTab
    } else {
      mainTab.value = 'overview'
    }
  }
)

// ---------- 生命周期 ----------

watch(
  () => props.code,
  async () => {
    quote.value = null
    quoteError.value = null
    bars.value = []
    flowToday.value = null
    flowHistory.value = null
    stockPredictions.value = []
    decisionContext.value = null
    defaultHoldDays.value = null
    backtest.value = null
    backtestError.value = null
    codeInput.value = ''
    loadedTabs.value = new Set() // reset lazy state
    await Promise.all([loadQuote(), loadDecisionContext()])
    ensureTabLoaded(mainTab.value)
  }
)

onMounted(async () => {
  await watchlistStore.fetchAll()
  await Promise.all([loadQuote(), loadDecisionContext()])
  ensureTabLoaded(mainTab.value)
  refreshTimer = window.setInterval(loadQuote, 10_000)
  themeObserver = new MutationObserver(() => void drawKLine())
  themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] })
})

onUnmounted(() => {
  if (refreshTimer) clearInterval(refreshTimer)
  themeObserver?.disconnect()
  if (klineChart.value) {
    klineChart.value.dispose()
    klineChart.value = null
  }
})
</script>

<template>
  <div class="min-h-screen bg-background pb-8">
    <!-- 顶部栏：返回 + 代码输入 -->
    <header class="flex items-center gap-2 bg-primary px-3 py-3 text-primary-foreground">
      <Button
        variant="ghost"
        size="sm"
        class="text-primary-foreground hover:bg-primary-foreground/20"
        @click="goBack"
      >
        ‹ 返回
      </Button>
      <Input
        v-model="codeInput"
        name="stock-code"
        autocomplete="off"
        aria-label="股票代码"
        placeholder="输入代码后回车…"
        class="h-8 w-40 border-primary-foreground/30 bg-primary-foreground/15 text-primary-foreground placeholder:text-primary-foreground/60"
        @keyup.enter="onCodeEnter"
      />
    </header>

    <div class="mx-auto max-w-3xl space-y-4 p-3">
      <!-- ============ 实时报价卡片 ============ -->
      <Card>
        <CardHeader class="pb-2">
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-2">
              <CardTitle class="text-lg">{{ quote?.name || code }}</CardTitle>
              <Badge variant="secondary" class="font-mono">{{ code }}</Badge>
            </div>
            <span v-if="quote" class="text-xs text-muted-foreground">
              {{ fmtAge(quote.data_age_seconds) }}
            </span>
          </div>
        </CardHeader>
        <CardContent class="space-y-4">
          <!-- 加载骨架 -->
          <template v-if="quoteLoading && !quote">
            <div class="flex items-baseline gap-3">
              <Skeleton class="h-10 w-32" />
              <Skeleton class="h-6 w-20" />
            </div>
            <Skeleton class="h-20 w-full" />
          </template>

          <template v-else-if="quote">
            <!-- 现价 + 涨跌 -->
            <div class="flex items-baseline gap-3">
              <span :class="cn('font-mono text-4xl font-bold', dirClass(quote.change_pct))">
                {{ fmtPrice(quote.price) }}
              </span>
              <span :class="cn('font-mono text-xl font-semibold', dirClass(quote.change_pct))">
                {{ dirSign(quote.change_pct) }}{{ fmtPrice(quote.change) }}
                ({{ fmtPct(quote.change_pct) }})
              </span>
            </div>

            <div class="flex flex-wrap items-center gap-2">
              <Button variant="outline" size="sm" :disabled="isWatched" @click="addToWatchlist">
                {{ isWatched ? '★ 已在自选' : '☆ 加自选' }}
              </Button>
              <Button size="sm" @click="askAgent">🤖 问问 AI</Button>
              <span v-if="actionMessage" role="status" class="text-xs text-muted-foreground">{{ actionMessage }}</span>
            </div>

            <div
              v-if="decisionContext?.holding"
              class="grid grid-cols-3 gap-2 rounded-lg bg-muted/60 p-3 text-sm"
            >
              <div>
                <p class="text-xs text-muted-foreground">当前持仓</p>
                <p class="mt-1 font-mono font-semibold">{{ decisionContext.holding.shares }} 股</p>
              </div>
              <div>
                <p class="text-xs text-muted-foreground">平均成本</p>
                <p class="mt-1 font-mono font-semibold">{{ fmtPrice(decisionContext.holding.avg_cost) }}</p>
              </div>
              <div>
                <p class="text-xs text-muted-foreground">浮动盈亏</p>
                <p
                  v-if="holdingPnl"
                  class="mt-1 font-mono font-semibold"
                  :class="dirClass(holdingPnl.pnl)"
                >
                  {{ dirSign(holdingPnl.pnl) }}{{ fmtMoney(holdingPnl.pnl) }} · {{ fmtPct(holdingPnl.pct) }}
                </p>
                <p v-else class="mt-1 text-muted-foreground">待行情</p>
              </div>
            </div>
            <div
              v-if="sourceBasket || decisionContext?.baskets.length"
              class="flex flex-wrap items-center gap-2 text-xs text-muted-foreground"
            >
              <RouterLink
                v-if="sourceBasket"
                :to="{ name: 'basket-detail', params: { id: sourceBasket.id } }"
                class="rounded-full bg-primary/10 px-2.5 py-1 text-primary hover:bg-primary/15 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
              >来自 {{ sourceBasket.name }}</RouterLink>
              <span v-if="decisionContext && decisionContext.baskets.length > (sourceBasket ? 1 : 0)">
                还属于 {{ decisionContext.baskets.length - (sourceBasket ? 1 : 0) }} 个篮子
              </span>
            </div>
          </template>

          <!-- 加载失败且没有旧报价：错误态 + 重试（不再是一张白卡） -->
          <ErrorState
            v-else-if="quoteError"
            :message="quoteErrorMessage"
            @retry="loadQuote"
          />
        </CardContent>
      </Card>

      <!-- ============ 主 Tab：概览 / 走势 / 资金 / 决策记录 ============ -->
      <Tabs v-model="mainTab">
        <TabsList class="grid w-full grid-cols-4">
          <TabsTrigger value="overview" class="text-sm">概览</TabsTrigger>
          <TabsTrigger value="chart" class="text-sm">走势</TabsTrigger>
          <TabsTrigger value="flow" class="text-sm">资金</TabsTrigger>
          <TabsTrigger value="decisions" class="text-sm">决策记录</TabsTrigger>
        </TabsList>

        <!-- ===== 概览 ===== -->
        <TabsContent value="overview">
          <Card v-if="quote">
            <CardContent class="pt-4">
              <Table>
                <TableBody>
                  <TableRow>
                    <TableCell class="w-1/4 py-2 text-xs text-muted-foreground">今开</TableCell>
                    <TableCell class="w-1/4 py-2 text-right font-mono text-sm">{{ fmtPrice(quote.open) }}</TableCell>
                    <TableCell class="w-1/4 py-2 text-xs text-muted-foreground">昨收</TableCell>
                    <TableCell class="w-1/4 py-2 text-right font-mono text-sm">{{ fmtPrice(quote.prev_close) }}</TableCell>
                  </TableRow>
                  <TableRow>
                    <TableCell class="py-2 text-xs text-muted-foreground">最高</TableCell>
                    <TableCell :class="cn('py-2 text-right font-mono text-sm', dirClassRef(quote.high, quote.prev_close))">{{ fmtPrice(quote.high) }}</TableCell>
                    <TableCell class="py-2 text-xs text-muted-foreground">最低</TableCell>
                    <TableCell :class="cn('py-2 text-right font-mono text-sm', dirClassRef(quote.low, quote.prev_close))">{{ fmtPrice(quote.low) }}</TableCell>
                  </TableRow>
                  <TableRow>
                    <TableCell class="py-2 text-xs text-muted-foreground">成交量</TableCell>
                    <TableCell class="py-2 text-right font-mono text-sm">{{ fmtWan(Number(quote.volume) / 100) }}手</TableCell>
                    <TableCell class="py-2 text-xs text-muted-foreground">成交额</TableCell>
                    <TableCell class="py-2 text-right font-mono text-sm">{{ fmtMoney(quote.turnover, 'yi') }}</TableCell>
                  </TableRow>
                  <TableRow>
                    <TableCell class="py-2 text-xs text-muted-foreground">换手</TableCell>
                    <TableCell class="py-2 text-right font-mono text-sm">{{ quote.turnover_rate ? `${quote.turnover_rate}%` : '-' }}</TableCell>
                    <TableCell class="py-2 text-xs text-muted-foreground">量比</TableCell>
                    <TableCell class="py-2 text-right font-mono text-sm">{{ quote.volume_ratio || '-' }}</TableCell>
                  </TableRow>
                  <TableRow>
                    <TableCell class="py-2 text-xs text-muted-foreground">PE</TableCell>
                    <TableCell class="py-2 text-right font-mono text-sm">{{ quote.pe || '-' }}</TableCell>
                    <TableCell class="py-2 text-xs text-muted-foreground">主力净流入</TableCell>
                    <TableCell :class="cn('py-2 text-right font-mono text-sm font-semibold', dirClass(quote.main_net_inflow))">
                      {{ dirSign(quote.main_net_inflow) }}{{ fmtMoney(quote.main_net_inflow, 'yi') }}
                    </TableCell>
                  </TableRow>
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </TabsContent>

        <!-- ===== 走势 ===== -->
        <TabsContent value="chart">
          <Card>
            <CardContent class="pt-4">
              <Tabs v-model="interval" class="w-full">
                <TabsList class="grid w-full grid-cols-7">
                  <TabsTrigger
                    v-for="i in intervals"
                    :key="i.key"
                    :value="i.key"
                    class="text-xs"
                    @click="changeInterval(i.key)"
                  >
                    {{ i.label }}
                  </TabsTrigger>
                </TabsList>
              </Tabs>
              <div id="kline" class="mt-3 h-[360px] w-full"></div>
            </CardContent>
          </Card>
        </TabsContent>

        <!-- ===== 资金 ===== -->
        <TabsContent value="flow">
          <Card>
            <CardContent class="space-y-4 pt-4">
              <Tabs v-model="flowTab">
            <TabsList>
              <TabsTrigger value="today" class="text-sm">日内</TabsTrigger>
              <TabsTrigger value="history" class="text-sm">历史</TabsTrigger>
            </TabsList>

            <!-- ===== 日内 ===== -->
            <TabsContent value="today" class="space-y-4">
              <!-- 累计汇总 -->
              <div v-if="flowToday?.cumulative" class="grid grid-cols-5 gap-1">
                <div class="rounded-md bg-muted/60 p-2 text-center">
                  <div class="mb-1 text-[10px] text-muted-foreground">主力净流入</div>
                  <div :class="cn('font-mono text-xs font-bold', dirClass(flowToday.cumulative.main_net))">
                    {{ dirSign(flowToday.cumulative.main_net) }}{{ fmtFlowWan(flowToday.cumulative.main_net) }}
                  </div>
                </div>
                <div class="rounded-md bg-muted/40 p-2 text-center">
                  <div class="mb-1 text-[10px] text-muted-foreground">超大单</div>
                  <div :class="cn('font-mono text-xs font-bold', dirClass(flowToday.cumulative.super_net))">
                    {{ dirSign(flowToday.cumulative.super_net) }}{{ fmtFlowWan(flowToday.cumulative.super_net) }}
                  </div>
                </div>
                <div class="rounded-md bg-muted/40 p-2 text-center">
                  <div class="mb-1 text-[10px] text-muted-foreground">大单</div>
                  <div :class="cn('font-mono text-xs font-bold', dirClass(flowToday.cumulative.big_net))">
                    {{ dirSign(flowToday.cumulative.big_net) }}{{ fmtFlowWan(flowToday.cumulative.big_net) }}
                  </div>
                </div>
                <div class="rounded-md bg-muted/40 p-2 text-center">
                  <div class="mb-1 text-[10px] text-muted-foreground">中单</div>
                  <div :class="cn('font-mono text-xs font-bold', dirClass(flowToday.cumulative.medium_net))">
                    {{ dirSign(flowToday.cumulative.medium_net) }}{{ fmtFlowWan(flowToday.cumulative.medium_net) }}
                  </div>
                </div>
                <div class="rounded-md bg-muted/40 p-2 text-center">
                  <div class="mb-1 text-[10px] text-muted-foreground">小单</div>
                  <div :class="cn('font-mono text-xs font-bold', dirClass(flowToday.cumulative.small_net))">
                    {{ dirSign(flowToday.cumulative.small_net) }}{{ fmtFlowWan(flowToday.cumulative.small_net) }}
                  </div>
                </div>
              </div>

              <!-- 日内分时折线 -->
              <div v-if="flowToday && flowToday.items.length">
                <div :class="dirClass(flowToday.cumulative?.main_net)">
                  <svg
                    :viewBox="`0 0 ${SVG_W} ${SVG_H_TODAY}`"
                    class="block w-full"
                    preserveAspectRatio="xMidYMid meet"
                  >
                    <line :x1="PAD_L" :y1="SVG_H_TODAY / 2" :x2="SVG_W - PAD_R" :y2="SVG_H_TODAY / 2" stroke="#eee" stroke-width="1" />
                    <polygon :points="todayFlowArea" fill="currentColor" fill-opacity="0.12" />
                    <polyline :points="todayFlowPoints" stroke="currentColor" stroke-width="1.5" fill="none" />
                  </svg>
                </div>
                <div class="flex justify-between px-1 pt-1 font-mono text-[10px] text-muted-foreground">
                  <span v-for="(t, i) in todayTimeLabels" :key="i">{{ t }}</span>
                </div>
              </div>
              <div v-else-if="!flowLoading" class="py-6 text-center text-sm text-muted-foreground">
                暂无日内数据（非盘中时段）
              </div>
            </TabsContent>

            <!-- ===== 历史 ===== -->
            <TabsContent value="history" class="space-y-4">
              <!-- 累计汇总 -->
              <div v-if="flowHistory?.cumulative" class="grid grid-cols-5 gap-1">
                <div class="rounded-md bg-muted/60 p-2 text-center">
                  <div class="mb-1 text-[10px] text-muted-foreground">主力净流入</div>
                  <div :class="cn('font-mono text-xs font-bold', dirClass(flowHistory.cumulative.main_net))">
                    {{ dirSign(flowHistory.cumulative.main_net) }}{{ fmtFlowWan(flowHistory.cumulative.main_net) }}
                  </div>
                </div>
                <div class="rounded-md bg-muted/40 p-2 text-center">
                  <div class="mb-1 text-[10px] text-muted-foreground">超大单</div>
                  <div :class="cn('font-mono text-xs font-bold', dirClass(flowHistory.cumulative.super_net))">
                    {{ dirSign(flowHistory.cumulative.super_net) }}{{ fmtFlowWan(flowHistory.cumulative.super_net) }}
                  </div>
                </div>
                <div class="rounded-md bg-muted/40 p-2 text-center">
                  <div class="mb-1 text-[10px] text-muted-foreground">大单</div>
                  <div :class="cn('font-mono text-xs font-bold', dirClass(flowHistory.cumulative.big_net))">
                    {{ dirSign(flowHistory.cumulative.big_net) }}{{ fmtFlowWan(flowHistory.cumulative.big_net) }}
                  </div>
                </div>
                <div class="rounded-md bg-muted/40 p-2 text-center">
                  <div class="mb-1 text-[10px] text-muted-foreground">中单</div>
                  <div :class="cn('font-mono text-xs font-bold', dirClass(flowHistory.cumulative.medium_net))">
                    {{ dirSign(flowHistory.cumulative.medium_net) }}{{ fmtFlowWan(flowHistory.cumulative.medium_net) }}
                  </div>
                </div>
                <div class="rounded-md bg-muted/40 p-2 text-center">
                  <div class="mb-1 text-[10px] text-muted-foreground">小单</div>
                  <div :class="cn('font-mono text-xs font-bold', dirClass(flowHistory.cumulative.small_net))">
                    {{ dirSign(flowHistory.cumulative.small_net) }}{{ fmtFlowWan(flowHistory.cumulative.small_net) }}
                  </div>
                </div>
              </div>

              <!-- 天数选择 -->
              <div class="flex gap-2">
                <Button
                  v-for="d in [7, 30, 90]"
                  :key="d"
                  :variant="flowDays === d ? 'default' : 'outline'"
                  size="sm"
                  class="h-7 rounded-full px-3 text-xs"
                  @click="changeFlowDays(d)"
                >
                  {{ d }}天
                </Button>
              </div>

              <!-- 历史柱状图 -->
              <div v-if="flowHistory && flowHistory.items.length">
                <svg
                  :viewBox="`0 0 ${SVG_W} ${SVG_H_HISTORY}`"
                  class="block w-full"
                  preserveAspectRatio="xMidYMid meet"
                >
                  <line
                    :x1="PAD_L" :y1="historyMidY"
                    :x2="SVG_W - PAD_R" :y2="historyMidY"
                    stroke="#ddd" stroke-width="1" stroke-dasharray="3,3"
                  />
                  <template v-for="(b, i) in historyBars" :key="i">
                    <rect :x="b.x" :y="b.y" :width="b.w" :height="b.h" :fill="b.color" rx="2" />
                    <text
                      :x="Number(b.x) + Number(b.w) / 2"
                      :y="b.labelY"
                      text-anchor="middle" font-size="8" fill="#999"
                    >{{ b.val }}</text>
                    <text
                      :x="Number(b.x) + Number(b.w) / 2"
                      :y="SVG_H_HISTORY - 6"
                      text-anchor="middle" font-size="8" fill="#aaa"
                    >{{ b.date }}</text>
                  </template>
                </svg>
              </div>
              <div v-else-if="!flowLoading" class="py-6 text-center text-sm text-muted-foreground">
                暂无历史数据
              </div>
            </TabsContent>
          </Tabs>
        </CardContent>
      </Card>
        </TabsContent>

        <!-- ===== 决策记录 ===== -->
        <TabsContent value="decisions">
          <div class="space-y-3">
            <!-- 回测面板 -->
            <Card>
              <CardContent class="space-y-3 pt-4">
                <div class="flex items-center justify-between gap-2">
                  <div>
                    <p class="text-sm font-medium">回测</p>
                    <p class="text-xs text-muted-foreground">{{ backtestSubtitle }}</p>
                  </div>
                  <Button
                    size="sm"
                    variant="outline"
                    :disabled="backtestLoading"
                    @click="runBacktest"
                  >
                    {{ backtestLoading ? '回测中…' : '运行回测' }}
                  </Button>
                </div>
                <p v-if="backtestError" class="text-xs text-destructive">{{ backtestError }}</p>
                <template v-if="backtest">
                  <p v-if="backtest.message" class="text-xs text-muted-foreground">
                    {{ backtest.message }}
                  </p>
                  <template v-else>
                    <p class="text-[10px] text-muted-foreground">
                      {{ backtest.start_date }} ~ {{ backtest.end_date }} · 持有 {{ backtest.hold_days }} 天
                    </p>
                    <div class="grid grid-cols-5 gap-1 text-center">
                      <div class="rounded-md bg-muted/60 p-2">
                        <div class="mb-1 text-[10px] text-muted-foreground">信号数</div>
                        <div class="font-mono text-xs font-bold">{{ backtest.total_signals }}</div>
                      </div>
                      <div class="rounded-md bg-muted/40 p-2">
                        <div class="mb-1 text-[10px] text-muted-foreground">胜率</div>
                        <div class="font-mono text-xs font-bold">{{ fmtWinRate(backtest.win_rate) }}</div>
                      </div>
                      <div class="rounded-md bg-muted/40 p-2">
                        <div class="mb-1 text-[10px] text-muted-foreground">平均收益</div>
                        <div
                          class="font-mono text-xs font-bold"
                          :class="backtest.avg_return_pct != null ? dirClass(backtest.avg_return_pct) : ''"
                        >{{ fmtReturnPct(backtest.avg_return_pct) }}</div>
                      </div>
                      <div class="rounded-md bg-muted/40 p-2">
                        <div class="mb-1 text-[10px] text-muted-foreground">最大回撤</div>
                        <div class="font-mono text-xs font-bold">{{ fmtDrawdownPct(backtest.max_drawdown_pct) }}</div>
                      </div>
                      <div class="rounded-md bg-muted/40 p-2">
                        <div class="mb-1 text-[10px] text-muted-foreground">夏普</div>
                        <div class="font-mono text-xs font-bold">{{ fmtSharpe(backtest.sharpe_ratio) }}</div>
                      </div>
                    </div>
                  </template>
                </template>
              </CardContent>
            </Card>

            <!-- 加载中 -->
            <div v-if="predictionsLoading" class="space-y-2">
              <div v-for="i in 2" :key="i" class="h-20 animate-pulse rounded-xl bg-muted" />
            </div>

            <!-- 预测记录列表 -->
            <template v-else>
              <Card v-for="p in stockPredictions" :key="p.id">
                <CardContent class="space-y-2 pt-4">
                  <div class="flex items-center justify-between">
                    <div class="flex items-center gap-2">
                      <span
                        class="rounded px-2 py-0.5 text-xs font-medium"
                        :class="predictionStatusBadge(p.status).class"
                      >
                        {{ predictionStatusBadge(p.status).label }}
                      </span>
                      <span class="text-sm font-medium">{{ p.prediction }}</span>
                    </div>
                    <span class="text-xs text-muted-foreground">
                      {{ p.timeframe }}
                    </span>
                  </div>

                  <!-- 目标价/入场价/止损 -->
                  <div v-if="p.target_price || p.entry_price" class="flex gap-4 text-xs text-muted-foreground">
                    <span v-if="p.entry_price">入场: ¥{{ p.entry_price }}</span>
                    <span v-if="p.target_price">目标: ¥{{ p.target_price }}</span>
                    <span v-if="p.stop_loss">止损: ¥{{ p.stop_loss }}</span>
                  </div>

                  <!-- 依据 -->
                  <p v-if="p.rationale" class="text-xs text-muted-foreground line-clamp-3">
                    {{ p.rationale }}
                  </p>

                  <!-- 验证结果 + 数据新鲜度 -->
                  <div v-if="p.verified_at" class="flex flex-wrap items-center gap-x-2 gap-y-1 border-t pt-2 text-xs">
                    <span class="text-muted-foreground">验证结果:</span>
                    <span v-if="p.actual_change_pct !== null" class="font-mono" :class="Number(p.actual_change_pct) >= 0 ? 'text-up' : 'text-down'">
                      {{ Number(p.actual_change_pct) >= 0 ? '+' : '' }}{{ Number(p.actual_change_pct).toFixed(2) }}%
                    </span>
                    <span class="text-muted-foreground">
                      · {{ verifyFreshnessText(p.data_coverage_at_verify) }}
                    </span>
                  </div>

                  <!-- 依据覆盖 -->
                  <div class="flex flex-wrap items-center gap-1.5 text-xs">
                    <span class="text-muted-foreground">依据覆盖:</span>
                    <template v-if="coverageBadgeLabels(p.data_coverage_at_creation)?.length">
                      <span
                        v-for="label in coverageBadgeLabels(p.data_coverage_at_creation)"
                        :key="label"
                        class="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground"
                      >{{ label }}</span>
                    </template>
                    <span v-else class="text-muted-foreground">未记录</span>
                  </div>

                  <!-- 时间 -->
                  <div class="flex flex-wrap items-center gap-x-3 text-[10px] text-muted-foreground">
                    <span>生成于 {{ new Date(p.created_at).toLocaleString('zh-CN') }}</span>
                    <span v-if="p.verified_at">验证于 {{ new Date(p.verified_at).toLocaleString('zh-CN') }}</span>
                    <span v-if="p.status === 'pending'">{{ pendingVerifyText(p) }}</span>
                  </div>
                </CardContent>
              </Card>

              <!-- 空状态 -->
              <Card v-if="stockPredictions.length === 0">
                <CardContent class="pt-6 text-center text-sm text-muted-foreground">
                  <p>该股暂无预测记录</p>
                  <Button size="sm" variant="outline" class="mt-3" @click="askAgent">
                    🤖 让 AI 生成预测
                  </Button>
                </CardContent>
              </Card>

              <!-- 查看全部预测的深链 -->
              <div class="text-center">
                <RouterLink to="/predictions" class="text-xs text-muted-foreground hover:text-foreground">
                  查看全部预测记录 →
                </RouterLink>
              </div>
            </template>
          </div>
        </TabsContent>
      </Tabs>
    </div>
  </div>
</template>
